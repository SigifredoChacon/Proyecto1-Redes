# Protocols/GoBackN/go_back_n.py
from Utils.types import Frame, FrameKind, EventType, Packet
from Utils.util import inc  # usamos inc modular
from Events.api import (
    wait_for_event, from_network_layer, to_physical_layer, from_physical_layer,
    to_network_layer, start_timer, stop_timer, start_ack_timer, stop_ack_timer,
    enable_network_layer, disable_network_layer
)

# Timers de DATA en Engine global: separo A/B con offsets (no tocamos Engine)
OFFSET_A = 0
OFFSET_B = 100


class SW1Peer:
    """
    Ventana deslizante de tamaño 1 (Stop-and-Wait) full-duplex con piggyback.
    - Números de secuencia: 1 bit -> {0,1}
    - Máx. 1 trama DATA outstanding por lado.
    - RX entrega solo en orden (acepta exactamente frame_expected).
    - Piggyback: cada DATA lleva ack = última en orden recibida.
    """

    def __init__(self, label: str, max_seq: int = 1):
        assert label in ("A", "B")
        # --- Parámetros del protocolo ---
        self.label = label
        self.max_seq = max_seq           # =1 => secuencias 0..1
        self.window = 1                  # ventana TX de tamaño 1

        # --- TX ---
        self.ack_expected = 0            # base de la ventana (única en vuelo)
        self.next_to_send = 0            # siguiente seq a usar (0 o 1)
        self.nbuffered = 0               # 0 o 1
        self.out_buf = {}                # seq -> Packet (solo la pendiente)

        # --- RX ---
        self.frame_expected = 0          # siguiente seq válida que espero

    # -------------------- helpers --------------------
    def tx_offset(self) -> int:
        return OFFSET_A if self.label == "A" else OFFSET_B

    def tx_window_has_space(self) -> bool:
        return self.nbuffered < self.window  # true si no hay DATA pendiente

    def last_in_order(self) -> int:
        """Última entregada = (frame_expected - 1) mod (max_seq+1)."""
        return (self.frame_expected + self.max_seq) % (self.max_seq + 1)

    def _in_window(self, a: int, x: int, b: int) -> bool:
        """
        Equivalente a between(a, x, b) de Tanenbaum, usando self.max_seq.
        Verdadero si (a <= x < b) en aritmética circular mod (max_seq+1).
        """
        m = self.max_seq + 1
        a %= m; x %= m; b %= m
        if a <= b:
            return a <= x < b
        else:
            return x >= a or x < b

    # -------------------- TX core --------------------
    def tx_push_new(self):
        """
        Toma paquete de app, lo etiqueta 'A>'/'B>', lo guarda en out_buf[next_to_send],
        envía DATA con piggyback y arranca timer. Aumenta nbuffered y avanza next_to_send.
        """
        p = from_network_layer()
        p_labeled = Packet(f"{self.label}>{p.data}")
        s = self.next_to_send

        self.out_buf[s] = p_labeled
        self.nbuffered = 1  # solo una en vuelo

        self._send_data(s)
        self.next_to_send = inc(s, self.max_seq)

    def _send_data(self, seq: int):
        """Construye y envía DATA(seq) con piggyback ack; (re)inicia timer de esa seq."""
        ack_pb = self.last_in_order()
        to_physical_layer(Frame(FrameKind.DATA, seq, ack_pb, self.out_buf[seq]))
        start_timer(self.tx_offset() + seq)

    def tx_consume_ack(self, a: int):
        """
        Procesa ACK (puro o piggyback). Con ventana=1, avanzamos si reconoce ack_expected.
        Usamos lógica circular con _in_window(ack_expected, a, next_to_send).
        """
        if self.nbuffered > 0 and self._in_window(self.ack_expected, a, self.next_to_send):
            # Apaga timer de la trama reconocida y libera buffer
            try:
                stop_timer(self.tx_offset() + self.ack_expected)
            except Exception:
                pass
            self.out_buf.pop(self.ack_expected, None)
            self.nbuffered = 0
            self.ack_expected = inc(self.ack_expected, self.max_seq)

    def tx_timeout(self, timed_seq: int):
        """
        TIMEOUT en Stop-and-Wait: retransmitimos **la única** DATA pendiente (si la hay).
        """
        if self.nbuffered == 0:
            return
        # timed_seq coincide con la seq pendiente (única)
        self._send_data(self.ack_expected)

    # -------------------- RX core --------------------
    def rx_handle_data(self, r_seq: int, info: Packet):
        """
        Acepta SOLO la seq esperada (entrega en orden). Duplicados se ignoran
        (pero se reconocerán por piggyback o ACK diferido).
        """
        if r_seq == self.frame_expected:
            to_network_layer(info)
            self.frame_expected = inc(self.frame_expected, self.max_seq)


# =====================================================================
#            DISPATCHER BIDIRECCIONAL (ventana 1, full-duplex)
# =====================================================================

def run_gbn_bidirectional(steps=2000, max_seq=1):
    """
    Mantengo el nombre para compatibilidad con tu runner, pero ahora ejecuta
    ventana deslizante de tamaño 1 (Stop-and-Wait con piggyback).
    """
    A = SW1Peer("A", max_seq=max_seq)
    B = SW1Peer("B", max_seq=max_seq)

    enable_network_layer()
    turn = 0
    processed = 0
    ack_owner = None   # "A" o "B": quién tiene pendiente ACK diferido

    while processed < steps:
        ev, payload = wait_for_event()

        if ev == EventType.NETWORK_LAYER_READY:
            served = False
            if turn % 2 == 0:
                if A.tx_window_has_space():
                    A.tx_push_new(); served = True
                    if ack_owner == "A":
                        try: stop_ack_timer()
                        except: pass
                        ack_owner = None
                elif B.tx_window_has_space():
                    B.tx_push_new(); served = True
                    if ack_owner == "B":
                        try: stop_ack_timer()
                        except: pass
                        ack_owner = None
            else:
                if B.tx_window_has_space():
                    B.tx_push_new(); served = True
                    if ack_owner == "B":
                        try: stop_ack_timer()
                        except: pass
                        ack_owner = None
                elif A.tx_window_has_space():
                    A.tx_push_new(); served = True
                    if ack_owner == "A":
                        try: stop_ack_timer()
                        except: pass
                        ack_owner = None

            if served: enable_network_layer()
            else:      disable_network_layer()
            turn += 1

        elif ev == EventType.FRAME_ARRIVAL:
            r = from_physical_layer(payload)
            if not r:
                processed += 1; continue

            if r.kind == FrameKind.DATA:
                data = r.info.data
                if data.startswith("A>"):
                    # B recibe a A
                    B.rx_handle_data(r.seq, r.info)
                    B.tx_consume_ack(r.ack)
                    # programa ACK diferido por si no puede piggybackear pronto
                    try: stop_ack_timer()
                    except: pass
                    start_ack_timer(); ack_owner = "B"
                elif data.startswith("B>"):
                    # A recibe a B
                    A.rx_handle_data(r.seq, r.info)
                    A.tx_consume_ack(r.ack)
                    try: stop_ack_timer()
                    except: pass
                    start_ack_timer(); ack_owner = "A"

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
            # Venció ACK diferido → manda ACK puro del dueño
            if ack_owner == "A":
                to_physical_layer(Frame(FrameKind.ACK, 0, A.last_in_order(), Packet("ACK:A")))
                ack_owner = None
            elif ack_owner == "B":
                to_physical_layer(Frame(FrameKind.ACK, 0, B.last_in_order(), Packet("ACK:B")))
                ack_owner = None
            enable_network_layer()

        elif ev == EventType.TIMEOUT:
            # TIMEOUT de DATA: retransmitir la única pendiente del dueño
            key = payload
            if key >= OFFSET_B:
                B.tx_timeout(key - OFFSET_B)
                if ack_owner == "B":
                    try: stop_ack_timer()
                    except: pass
                    ack_owner = None
            else:
                A.tx_timeout(key - OFFSET_A)
                if ack_owner == "A":
                    try: stop_ack_timer()
                    except: pass
                    ack_owner = None
            enable_network_layer()

        processed += 1
