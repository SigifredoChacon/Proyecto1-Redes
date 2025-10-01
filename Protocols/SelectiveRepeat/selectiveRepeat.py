from Utils.types import Frame, FrameKind, EventType, Packet
from Utils.util import inc, between
from Events.api import (
    wait_for_event, from_network_layer, to_physical_layer, from_physical_layer,
    to_network_layer, start_timer, stop_timer, start_ack_timer, stop_ack_timer,
    enable_network_layer, disable_network_layer
)

OFFSET_A = 0
OFFSET_B = 100

class SRPeerUni:
    """
    Un extremo Selective Repeat (estado TX/RX) con:
      - Ventana SR, timers por trama (offset A/B),
      - RX con arrived[]/in_buf[] y entrega en orden,
      - ACK SELECTIVO (ack_pending_seq) + piggyback oportunista,
      - De-dupe por epoch: evita doble envío de la misma seq en el mismo tick.
    """
    def __init__(self, label: str, max_seq: int = 7):
        assert label in ("A", "B")
        self.label = label
        self.max_seq = max_seq
        self.nr_bufs = (max_seq + 1) // 2

        # ----- Estado TX -----
        self.next_to_send = 0
        self.out_buf = {}  # seq -> Packet

        # ----- Estado RX -----
        self.frame_expected = 0
        self.too_far = self.nr_bufs
        self.arrived = [False] * self.nr_bufs
        self.in_buf = [None] * self.nr_bufs

        # ACK selectivo pendiente para piggyback o ACK puro
        self.ack_pending_seq = None

        # De-dupe por epoch: recordatorio del último epoch en que se envió cada seq
        self._last_sent_epoch = {}  # seq -> epoch

    # -------- TX helpers --------
    def tx_window_has_space(self) -> bool:
        return len(self.out_buf) < self.nr_bufs

    def tx_offset(self) -> int:
        return OFFSET_A if self.label == "A" else OFFSET_B

    def last_in_order(self) -> int:
        """Último en orden ya entregado = frame_expected - 1 (mod max_seq+1)."""
        return (self.frame_expected + self.max_seq) % (self.max_seq + 1)

    def _should_skip_send_this_epoch(self, seq: int, epoch: int) -> bool:
        """Evita doble envío de la misma seq dentro del mismo tick/epoch."""
        return self._last_sent_epoch.get(seq) == epoch

    def _mark_sent_epoch(self, seq: int, epoch: int):
        self._last_sent_epoch[seq] = epoch

    def tx_send_data(self, epoch: int):
        """
        Saca Packet, etiqueta 'A>'/'B>', arma DATA:
          - seq = next_to_send
          - ack = ack_pending_seq (selectivo) o last_in_order() (acumulativo)
        Inicia timer (offset+seq) y avanza next_to_send.
        De-dupe: no repite la misma seq en el mismo epoch.
        """
        s = self.next_to_send
        if self._should_skip_send_this_epoch(s, epoch):
            return  # de-dupe

        p = from_network_layer()
        p_labeled = Packet(f"{self.label}>{p.data}")

        self.out_buf[s] = p_labeled
        ack_pb = self.ack_pending_seq if self.ack_pending_seq is not None else self.last_in_order()
        to_physical_layer(Frame(FrameKind.DATA, s, ack_pb, p_labeled))
        self._mark_sent_epoch(s, epoch)

        start_timer(self.tx_offset() + s)
        self.next_to_send = inc(s, self.max_seq)

        # opcional: ya piggybackeado → limpia para no re-ACKear igual
        self.ack_pending_seq = None

    def tx_ack_one(self, a: int):
        """Procesa ACK selectivo 'a' si aún está pendiente."""
        if a in self.out_buf:
            try:
                stop_timer(self.tx_offset() + a)
            except Exception:
                pass
            self.out_buf.pop(a, None)

    def tx_retransmit_one(self, seq: int, epoch: int):
        """Retransmite solo 'seq' si aún está pendiente. De-dupe por epoch."""
        if seq in self.out_buf:
            if self._should_skip_send_this_epoch(seq, epoch):
                return  # de-dupe (evita doblete inmediato)
            ack_pb = self.ack_pending_seq if self.ack_pending_seq is not None else self.last_in_order()
            to_physical_layer(Frame(FrameKind.DATA, seq, ack_pb, self.out_buf[seq]))
            self._mark_sent_epoch(seq, epoch)
            start_timer(self.tx_offset() + seq)

    # -------- RX helpers --------
    def rx_accept_and_deliver(self, r_seq: int, info: Packet):
        """Acepta dentro de [frame_expected, too_far), bufferiza y entrega en orden."""
        if between(self.frame_expected, r_seq, self.too_far):
            idx = r_seq % self.nr_bufs
            if not self.arrived[idx]:
                self.arrived[idx] = True
                self.in_buf[idx] = info

            while self.arrived[self.frame_expected % self.nr_bufs]:
                to_network_layer(self.in_buf[self.frame_expected % self.nr_bufs])
                self.arrived[self.frame_expected % self.nr_bufs] = False
                self.in_buf[self.frame_expected % self.nr_bufs] = None
                self.frame_expected = inc(self.frame_expected, self.max_seq)
                self.too_far = inc(self.too_far, self.max_seq)

# =====================================================================
#                       DISPATCHER BIDIRECCIONAL (con PB selectivo)
# =====================================================================

def run_sr_bidirectional(steps=1000, max_seq=7):
    """
    SR bidireccional con:
      - ACK selectivo (ack_pending_seq),
      - Piggyback oportunista,
      - De-dupe por epoch para evitar dobletes inmediatos,
      - Retransmisión selectiva por TIMEOUT (si sigue pendiente).
    """
    A = SRPeerUni("A", max_seq=max_seq)
    B = SRPeerUni("B", max_seq=max_seq)

    enable_network_layer()

    turn = 0
    processed = 0
    ack_owner = None
    epoch = 0  # ← contador de 'ticks' del bucle

    while processed < steps:
        ev, payload = wait_for_event()

        if ev == EventType.NETWORK_LAYER_READY:
            served = False
            if turn % 2 == 0:
                if A.tx_window_has_space():
                    A.tx_send_data(epoch); served = True
                    if ack_owner == "A":
                        try: stop_ack_timer()
                        except Exception: pass
                        ack_owner = None
                elif B.tx_window_has_space():
                    B.tx_send_data(epoch); served = True
                    if ack_owner == "B":
                        try: stop_ack_timer()
                        except Exception: pass
                        ack_owner = None
            else:
                if B.tx_window_has_space():
                    B.tx_send_data(epoch); served = True
                    if ack_owner == "B":
                        try: stop_ack_timer()
                        except Exception: pass
                        ack_owner = None
                elif A.tx_window_has_space():
                    A.tx_send_data(epoch); served = True
                    if ack_owner == "A":
                        try: stop_ack_timer()
                        except Exception: pass
                        ack_owner = None

            if not served:
                disable_network_layer()
            else:
                enable_network_layer()
            turn += 1

        elif ev == EventType.FRAME_ARRIVAL:
            r = from_physical_layer(payload)
            if not r:
                processed += 1; epoch += 1
                continue

            if r.kind == FrameKind.DATA:
                data = r.info.data
                if data.startswith("A>"):
                    # RX en B (A->B)
                    B.rx_accept_and_deliver(r.seq, Packet(data[2:]))

                    # Consumir ACK piggyback que llegó (confirma B->A)
                    B.tx_ack_one(r.ack)

                    # Registrar ACK selectivo pendiente (para A)
                    B.ack_pending_seq = r.seq

                    # Piggyback oportunista: enviar YA si hay ventana
                    if B.tx_window_has_space():
                        try: stop_ack_timer()
                        except Exception: pass
                        ack_owner = None
                        B.tx_send_data(epoch)  # llevará ack = ack_pending_seq
                    else:
                        try: stop_ack_timer()
                        except Exception: pass
                        start_ack_timer()
                        ack_owner = "B"

                    enable_network_layer()

                elif data.startswith("B>"):
                    # RX en A (B->A)
                    A.rx_accept_and_deliver(r.seq, Packet(data[2:]))

                    # Consumir ACK piggyback que llegó (confirma A->B)
                    A.tx_ack_one(r.ack)

                    # Registrar ACK selectivo pendiente (para B)
                    A.ack_pending_seq = r.seq

                    if A.tx_window_has_space():
                        try: stop_ack_timer()
                        except Exception: pass
                        ack_owner = None
                        A.tx_send_data(epoch)
                    else:
                        try: stop_ack_timer()
                        except Exception: pass
                        start_ack_timer()
                        ack_owner = "A"

                    enable_network_layer()

                else:
                    pass

            elif r.kind == FrameKind.ACK:
                tag = r.info.data
                if tag == "ACK:A":
                    B.tx_ack_one(r.ack)
                    enable_network_layer()
                elif tag == "ACK:B":
                    A.tx_ack_one(r.ack)
                    enable_network_layer()
                else:
                    pass

        elif ev == EventType.ACK_TIMEOUT:
            # ACK puro: enviar selectivo si hay; si no, acumulativo
            if ack_owner == "A":
                ack_seq = A.ack_pending_seq if A.ack_pending_seq is not None else A.last_in_order()
                to_physical_layer(Frame(FrameKind.ACK, 0, ack_seq, Packet("ACK:A")))
                A.ack_pending_seq = None
                ack_owner = None
            elif ack_owner == "B":
                ack_seq = B.ack_pending_seq if B.ack_pending_seq is not None else B.last_in_order()
                to_physical_layer(Frame(FrameKind.ACK, 0, ack_seq, Packet("ACK:B")))
                B.ack_pending_seq = None
                ack_owner = None

            enable_network_layer()

        elif ev == EventType.TIMEOUT:
            # Retransmisión selectiva (si sigue pendiente)
            key = payload  # en tu Engine es 'seq' con offset
            if key >= OFFSET_B:
                B.tx_retransmit_one(key - OFFSET_B, epoch)
            else:
                A.tx_retransmit_one(key - OFFSET_A, epoch)
            enable_network_layer()

        processed += 1
        epoch += 1