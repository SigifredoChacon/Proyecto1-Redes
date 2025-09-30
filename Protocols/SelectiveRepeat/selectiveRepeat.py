
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
    Un extremo Selective Repeat (estado TX/RX).
    - TX: ventana SR con timers por trama (start/stop_timer con offset por peer)
    - RX: ventana SR con arrived[]/in_buf[] y entrega en orden
    - Piggyback: cada DATA sale con ack = (frame_expected - 1) mod (max_seq+1)
    """
    def __init__(self, label: str, max_seq: int = 7):
        assert label in ("A", "B")
        self.label = label
        self.max_seq = max_seq
        self.nr_bufs = (max_seq + 1) // 2

        # ----- Estado TX -----
        self.next_to_send = 0
        self.out_buf = {}

        # ----- Estado RX -----
        self.frame_expected = 0
        self.too_far = self.nr_bufs
        self.arrived = [False] * self.nr_bufs
        self.in_buf = [None] * self.nr_bufs

    # -------- TX helpers --------
    def tx_window_has_space(self) -> bool:
        return len(self.out_buf) < self.nr_bufs

    def tx_offset(self) -> int:
        return OFFSET_A if self.label == "A" else OFFSET_B

    def last_in_order(self) -> int:
        """Último en orden ya entregado = frame_expected - 1 (mod max_seq+1)."""
        return (self.frame_expected + self.max_seq) % (self.max_seq + 1)

    def tx_send_data(self):
        """
        Saca un Packet de la app, lo etiqueta 'A>'/'B>', arma una DATA:
          - seq = next_to_send
          - ack = last_in_order()   (PIGGYBACK)
        Inicia DATA timer (offset+seq) y avanza next_to_send.
        """
        p = from_network_layer()
        p_labeled = Packet(f"{self.label}>{p.data}")

        s = self.next_to_send
        self.out_buf[s] = p_labeled

        ack_pb = self.last_in_order()
        to_physical_layer(Frame(FrameKind.DATA, s, ack_pb, p_labeled))


        start_timer(self.tx_offset() + s)

        self.next_to_send = inc(s, self.max_seq)

    def tx_ack_one(self, a: int):
        """Procesa (piggyback) ACK selectivo 'a' si sigue pendiente."""
        if a in self.out_buf:
            try:
                stop_timer(self.tx_offset() + a)
            except Exception:
                pass
            self.out_buf.pop(a, None)

    def tx_retransmit_one(self, seq: int):
        """Retransmite solo esa seq si aún está pendiente (SR)."""
        if seq in self.out_buf:

            ack_pb = self.last_in_order()
            to_physical_layer(Frame(FrameKind.DATA, seq, ack_pb, self.out_buf[seq]))
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
#                       DISPATCHER BIDIRECCIONAL (con PB)
# =====================================================================

def run_sr_bidirectional(steps=1000, max_seq=7):
    """
    Bucle central:
      - Alterna NETWORK_LAYER_READY entre A/B si hay espacio (produce DATA con piggyback).
      - FRAME_ARRIVAL:
          * DATA "A>..." la procesa B (RX), B consume piggyback r.ack, difiere ACK (ack_timer).
          * DATA "B>..." la procesa A, A consume piggyback r.ack, difiere ACK.
          * ACK puro: enruta a emisor opuesto (como antes).
      - TIMEOUT (DATA): usa offsets para A/B y retransmite solo esa seq (SR).
      - ACK_TIMEOUT: envía ACK puro del último en orden del peer dueño del ACK diferido.
    """
    A = SRPeerUni("A", max_seq=max_seq)
    B = SRPeerUni("B", max_seq=max_seq)

    enable_network_layer()

    turn = 0
    processed = 0
    ack_owner = None

    while processed < steps:
        ev, payload = wait_for_event()

        if ev == EventType.NETWORK_LAYER_READY:
            served = False
            if turn % 2 == 0:
                if A.tx_window_has_space():
                    A.tx_send_data(); served = True

                    if ack_owner == "A":
                        try: stop_ack_timer()
                        except Exception: pass
                        ack_owner = None
                elif B.tx_window_has_space():
                    B.tx_send_data(); served = True
                    if ack_owner == "B":
                        try: stop_ack_timer()
                        except Exception: pass
                        ack_owner = None
            else:
                if B.tx_window_has_space():
                    B.tx_send_data(); served = True
                    if ack_owner == "B":
                        try: stop_ack_timer()
                        except Exception: pass
                        ack_owner = None
                elif A.tx_window_has_space():
                    A.tx_send_data(); served = True
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
                processed += 1
                continue

            if r.kind == FrameKind.DATA:
                data = r.info.data
                if data.startswith("A>"):

                    B.rx_accept_and_deliver(r.seq, Packet(data[2:]))


                    B.tx_ack_one(r.ack)


                    try: stop_ack_timer()
                    except Exception: pass
                    start_ack_timer()
                    ack_owner = "B"

                    enable_network_layer()

                elif data.startswith("B>"):

                    A.rx_accept_and_deliver(r.seq, Packet(data[2:]))


                    A.tx_ack_one(r.ack)


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

            if ack_owner == "A":
                ack_seq = A.last_in_order()
                to_physical_layer(Frame(FrameKind.ACK, 0, ack_seq, Packet("ACK:A")))
                ack_owner = None
            elif ack_owner == "B":
                ack_seq = B.last_in_order()
                to_physical_layer(Frame(FrameKind.ACK, 0, ack_seq, Packet("ACK:B")))
                ack_owner = None

            enable_network_layer()

        elif ev == EventType.TIMEOUT:

            key = payload
            if key >= OFFSET_B:
                B.tx_retransmit_one(key - OFFSET_B)
            else:
                A.tx_retransmit_one(key - OFFSET_A)
            enable_network_layer()

        processed += 1
