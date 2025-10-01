# Protocols/GoBackN/go_back_n.py  (versión con epoch de-dupe + piggyback oportunista)
from Utils.types import Frame, FrameKind, EventType, Packet
from Utils.util import inc, between
from Events.api import (
    wait_for_event, from_network_layer, to_physical_layer, from_physical_layer,
    to_network_layer, start_timer, stop_timer, start_ack_timer, stop_ack_timer,
    enable_network_layer, disable_network_layer
)

OFFSET_A = 0
OFFSET_B = 100

class GBNPeer:
    def __init__(self, label: str, max_seq: int = 7):
        assert label in ("A", "B")
        self.label = label
        self.max_seq = max_seq
        self.window = max_seq  # tamaño ventana GBN (≈ max outstanding)

        # ----- Estado TX -----
        self.ack_expected = 0     # base (primera no-ACKeada)
        self.next_to_send = 0     # siguiente seq libre para enviar
        self.nbuffered = 0        # outstanding count
        self.out_buf = {}         # seq -> Packet

        # ----- Estado RX -----
        self.frame_expected = 0   # siguiente en orden (GBN descarta fuera de orden)

        # ----- De-dupe por epoch: evita doble envío de la MISMA seq en el mismo tick -----
        self._last_sent_epoch = {}  # seq -> epoch

    # -------------------- helpers --------------------
    def tx_offset(self) -> int:
        return OFFSET_A if self.label == "A" else OFFSET_B

    def tx_window_has_space(self) -> bool:
        return self.nbuffered < self.window

    def last_in_order(self) -> int:
        """Última entregada = (frame_expected - 1) mod (max_seq+1)."""
        return (self.frame_expected + self.max_seq) % (self.max_seq + 1)

    def _should_skip_send_this_epoch(self, seq: int, epoch: int) -> bool:
        return self._last_sent_epoch.get(seq) == epoch

    def _mark_sent_epoch(self, seq: int, epoch: int):
        self._last_sent_epoch[seq] = epoch

    # -------------------- TX core --------------------
    def tx_push_new(self, epoch: int):
        """
        Toma paquete de app, lo etiqueta 'A>'/'B>', lo guarda en out_buf[next_to_send],
        envía DATA con piggyback y arranca timer. Aumenta nbuffered y next_to_send.
        """
        p = from_network_layer()
        p_labeled = Packet(f"{self.label}>{p.data}")
        s = self.next_to_send

        self.out_buf[s] = p_labeled
        self.nbuffered += 1

        self._send_data(s, epoch)            # ← pasa epoch p/ de-dupe de este tick
        self.next_to_send = inc(s, self.max_seq)

    def _send_data(self, seq: int, epoch: int):
        """
        Construye y envía DATA(seq) con piggyback ack; (re)inicia timer de esa seq.
        De-dupe: si ya mandamos esta seq en este epoch, no volver a mandarla.
        """
        if self._should_skip_send_this_epoch(seq, epoch):
            return
        ack_pb = self.last_in_order()  # GBN usa ACK acumulativo (última en orden)
        to_physical_layer(Frame(FrameKind.DATA, seq, ack_pb, self.out_buf[seq]))
        self._mark_sent_epoch(seq, epoch)
        start_timer(self.tx_offset() + seq)

    def tx_consume_ack(self, a: int):
        """
        Procesa ACK CUMULATIVO (puro o piggyback). Avanza ack_expected mientras
        ack_expected <= a < next_to_send (circularmente), apagando timers y
        liberando out_buf. (mismo patrón que Tanenbaum)
        """
        while (self.nbuffered > 0) and between(self.ack_expected, a, self.next_to_send):
            old = self.ack_expected
            try:
                stop_timer(self.tx_offset() + old)
            except Exception:
                pass
            self.out_buf.pop(old, None)
            self.nbuffered -= 1
            self.ack_expected = inc(self.ack_expected, self.max_seq)

    def tx_timeout(self, timed_seq: int, epoch: int):
        """
        Cualquier TIMEOUT de una outstanding provoca reenvío de TODAS las outstanding
        comenzando en ack_expected (Go-Back-N). De-dupe por epoch en cada seq.
        """
        if self.nbuffered == 0:
            return
        s = self.ack_expected
        for _ in range(self.nbuffered):
            self._send_data(s, epoch)  # respeta de-dupe en este tick
            s = inc(s, self.max_seq)

    # -------------------- RX core --------------------
    def rx_handle_data(self, r_seq: int, info: Packet):
        """
        Acepta SOLO la seq esperada (entrega en orden). Duplicados/adelantadas se ignoran.
        """
        if r_seq == self.frame_expected:
            to_network_layer(info)
            self.frame_expected = inc(self.frame_expected, self.max_seq)


def run_gbn_bidirectional(steps=2000, max_seq=7):
    """
    GBN bidireccional con:
      - De-dupe por epoch (evita doble envío de misma seq en el mismo tick),
      - Piggyback ACK acumulativo,
      - Reenvío oportunista (si hay ventana) al recibir DATA, para piggybackear el ACK,
      - Timeout GBN: reenvía TODAS las outstanding desde base (sin cambiar semántica).
    """
    A = GBNPeer("A", max_seq=max_seq)
    B = GBNPeer("B", max_seq=max_seq)

    enable_network_layer()
    turn = 0
    processed = 0
    ack_owner = None
    epoch = 0  # contador de “ticks” del bucle (no toca Engine)

    while processed < steps:
        ev, payload = wait_for_event()

        if ev == EventType.NETWORK_LAYER_READY:
            served = False
            if turn % 2 == 0:
                if A.tx_window_has_space():
                    A.tx_push_new(epoch); served = True
                    if ack_owner == "A":
                        try: stop_ack_timer()
                        except: pass
                        ack_owner = None
                elif B.tx_window_has_space():
                    B.tx_push_new(epoch); served = True
                    if ack_owner == "B":
                        try: stop_ack_timer()
                        except: pass
                        ack_owner = None
            else:
                if B.tx_window_has_space():
                    B.tx_push_new(epoch); served = True
                    if ack_owner == "B":
                        try: stop_ack_timer()
                        except: pass
                        ack_owner = None
                elif A.tx_window_has_space():
                    A.tx_push_new(epoch); served = True
                    if ack_owner == "A":
                        try: stop_ack_timer()
                        except: pass
                        ack_owner = None

            if served:
                enable_network_layer()
            else:
                disable_network_layer()
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
                    B.rx_handle_data(r.seq, r.info)
                    # Consumir ACK acumulativo piggyback que llegó (confirma B->A)
                    B.tx_consume_ack(r.ack)

                    # Delayed-ACK (por si no hay DATA pronto para piggyback)
                    try: stop_ack_timer()
                    except: pass
                    start_ack_timer(); ack_owner = "B"

                    # === Reenvío oportunista (opcional/“agresivo”): ===
                    # si hay espacio en ventana, manda YA una DATA de B para piggybackear el ACK.
                    if B.tx_window_has_space():
                        try: stop_ack_timer()
                        except: pass
                        ack_owner = None
                        B.tx_push_new(epoch)   # usa from_network_layer() ahora mismo
                    # (si no hay espacio: se queda el ACK diferido)

                elif data.startswith("B>"):
                    # RX en A (B->A)
                    A.rx_handle_data(r.seq, r.info)
                    A.tx_consume_ack(r.ack)

                    try: stop_ack_timer()
                    except: pass
                    start_ack_timer(); ack_owner = "A"

                    if A.tx_window_has_space():
                        try: stop_ack_timer()
                        except: pass
                        ack_owner = None
                        A.tx_push_new(epoch)

                # si al menos uno tiene espacio, deja habilitada la app
                if A.tx_window_has_space() or B.tx_window_has_space():
                    enable_network_layer()

            elif r.kind == FrameKind.ACK:
                tag = r.info.data
                if tag == "ACK:A":
                    B.tx_consume_ack(r.ack)
                elif tag == "ACK:B":
                    A.tx_consume_ack(r.ack)
                if A.tx_window_has_space() or B.tx_window_has_space():
                    enable_network_layer()

        elif ev == EventType.ACK_TIMEOUT:
            # ACK puro acumulativo (GBN): last_in_order()
            if ack_owner == "A":
                to_physical_layer(Frame(FrameKind.ACK, 0, A.last_in_order(), Packet("ACK:A")))
                ack_owner = None
            elif ack_owner == "B":
                to_physical_layer(Frame(FrameKind.ACK, 0, B.last_in_order(), Packet("ACK:B")))
                ack_owner = None
            enable_network_layer()

        elif ev == EventType.TIMEOUT:
            key = payload
            if key >= OFFSET_B:
                B.tx_timeout(key - OFFSET_B, epoch)  # reenvía TODAS desde base
                if ack_owner == "B":
                    try: stop_ack_timer()
                    except: pass
                    ack_owner = None
            else:
                A.tx_timeout(key - OFFSET_A, epoch)
                if ack_owner == "A":
                    try: stop_ack_timer()
                    except: pass
                    ack_owner = None
            enable_network_layer()

        processed += 1
        epoch += 1