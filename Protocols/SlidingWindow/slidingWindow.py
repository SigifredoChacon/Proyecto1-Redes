# Protocols/SlidingWindow/slidingWindow.py
# Stop-and-Wait (ventana=1) full-duplex sin piggyback oportunista,
# con piggyback normal en NETWORK_LAYER_READY y ACK puro diferido.
# Compatible con Engine one-shot (ready_on_enable=True).

from Utils.types import Frame, FrameKind, EventType, Packet
from Utils.util import inc
from Events.api import (
    wait_for_event, from_network_layer, to_physical_layer, from_physical_layer,
    to_network_layer, start_timer, stop_timer, start_ack_timer, stop_ack_timer,
    enable_network_layer, disable_network_layer
)
import random  # lotería 50/50

# Offsets de timers para separar A y B en el Engine global
OFFSET_A = 0
OFFSET_B = 100


class SW1Peer:
    """
    Stop-and-Wait full-duplex (W=1) con:
      - timer único de DATA (para la trama en vuelo),
      - piggyback normal (solo al enviar DATA en READY),
      - ACK diferido (ACK puro si no se alcanza a piggybackear),
      - de-dupe por epoch para evitar doble envío en el mismo tick.
    """
    def __init__(self, label: str):
        assert label in ("A", "B")
        self.label = label

        # ---- Estado TX ----
        self.seq = 0                 # siguiente seq a usar en TX
        self.ack_expected = 0        # ACK que libera la DATA en vuelo
        self.waiting = False         # hay DATA en vuelo
        self.out_buf = {}            # seq -> Packet (en SW hay a lo sumo 1)

        # ---- Estado RX ----
        self.frame_expected = 0      # próxima DATA válida a aceptar

        # ---- ACK selectivo pendiente (para piggyback o ACK puro) ----
        # En SW, el ACK acumulativo "último correcto" = frame_expected ^ 1
        # Guardamos un "pendiente" para piggyback/ACK puro.
        self.ack_pending_seq = None  # último DATA correcto recibido (o None)

        # ---- De-dupe por epoch ----
        self._last_sent_epoch = {}   # seq -> epoch del último envío

    # --- utilidades ---
    def tx_offset(self) -> int:
        return OFFSET_A if self.label == "A" else OFFSET_B

    def last_in_order(self) -> int:
        # En SW acumulamos: último correcto = frame_expected ^ 1
        return self.frame_expected ^ 1

    def _should_skip_send_this_epoch(self, seq: int, epoch: int) -> bool:
        return self._last_sent_epoch.get(seq) == epoch

    def _mark_sent_epoch(self, seq: int, epoch: int):
        self._last_sent_epoch[seq] = epoch

    def tx_window_has_space(self) -> bool:
        # SW: espacio si no hay en vuelo
        return not self.waiting

    # --- TX: nuevo envío ---
    def tx_push_new(self, epoch: int):
        """Saca de la network layer, etiqueta y envía DATA con piggyback acumulativo."""
        s = self.seq
        if self._should_skip_send_this_epoch(s, epoch):
            return  # de-dupe intra-tick

        p = from_network_layer()
        p_labeled = Packet(f"{self.label}>{p.data}")
        self.out_buf[s] = p_labeled

        # Piggyback acumulativo: si tengo un ACK pendiente, úsalo; si no, last_in_order()
        ack_pb = self.ack_pending_seq if self.ack_pending_seq is not None else self.last_in_order()
        to_physical_layer(Frame(FrameKind.DATA, s, ack_pb, p_labeled))
        self._mark_sent_epoch(s, epoch)
        start_timer(self.tx_offset() + s)

        self.waiting = True
        self.ack_expected = s
        # Limpia el pendiente (ya piggybackeado si lo había)
        self.ack_pending_seq = None

    # --- TX: consumir ACK piggyback (o puro) ---
    def tx_consume_ack(self, a: int):
        """Libera la DATA en vuelo si el ACK confirma la base (SW: ack_expected)."""
        if self.waiting and a == self.ack_expected:
            try:
                stop_timer(self.tx_offset() + self.ack_expected)
            except Exception:
                pass
            # libera
            self.out_buf.pop(self.ack_expected, None)
            self.waiting = False
            # siguiente seq
            self.seq ^= 1
            self.ack_expected ^= 1

    # --- TX: retransmisión por TIMEOUT ---
    def tx_timeout(self, timed_key: int, epoch: int):
        """Reenvía la DATA base (SW: la única) si sigue pendiente."""
        # timed_key llega como OFFSET+seq
        s = timed_key - self.tx_offset()
        if not self.waiting or s != self.ack_expected:
            return
        if self._should_skip_send_this_epoch(s, epoch):
            return  # de-dupe intra-tick

        ack_pb = self.ack_pending_seq if self.ack_pending_seq is not None else self.last_in_order()
        to_physical_layer(Frame(FrameKind.DATA, s, ack_pb, self.out_buf[s]))
        self._mark_sent_epoch(s, epoch)
        start_timer(self.tx_offset() + s)

    # --- RX: aceptar DATA y marcar ACK pendiente ---
    def rx_handle_data(self, r_seq: int, info: Packet):
        """Acepta solo la DATA esperada; dup/adelantadas se ignoran. Registra ACK pendiente."""
        if r_seq == self.frame_expected:
            to_network_layer(info)     # ¡mantén 'A>'/'B>' para tus métricas!
            self.frame_expected ^= 1
        # El ACK debido al emisor es el "último correcto". Para SW, si es duplicado,
        # r_seq == frame_expected ^ 1; si es nuevo, ya viramos frame_expected.
        self.ack_pending_seq = self.last_in_order()


# =========================================================
#                  BUCLE BIDIRECCIONAL (SW=1)
#   - Lotería estricta 50/50 por READY (como SR/GBN).
#   - SIN piggyback oportunista (NO se envía DATA en FRAME_ARRIVAL).
#   - ACK puro diferido con 'ack_owner'.
#   - Compatible con motores one-shot (ready_on_enable=True)
#     usando rearm_ready() para agendar READY cuando haya espacio.
# =========================================================

def run_gbn_bidirectional(steps=2000, max_seq=1):
    A = SW1Peer("A")
    B = SW1Peer("B")

    processed = 0
    epoch = 0                # contador de ticks/iteraciones
    ack_owner = None         # None | "A" | "B"

    # ---- helpers para motores one-shot READY ----
    def want_app_ready() -> bool:
        # Si alguno tiene espacio (no está esperando ACK), podemos empujar app.
        return A.tx_window_has_space() or B.tx_window_has_space()

    def rearm_ready():
        # OFF->ON agenda un READY nuevo en motores con ready_on_enable=True
        disable_network_layer()
        enable_network_layer()

    # Asegura el primer READY
    rearm_ready()

    # Métricas opcionales (si quieres ver comportamiento, imprime al final)
    pb_ready = 0   # piggyback al atender READY natural
    ack_pure = 0   # ACK puros por ACK_TIMEOUT

    while processed < steps:
        # Safe wait: si la cola se vaciara (edge case), rearmamos READY y salimos si persiste.
        try:
            ev, payload = wait_for_event()
        except IndexError:
            rearm_ready()
            try:
                ev, payload = wait_for_event()
            except IndexError:
                break

        if ev == EventType.NETWORK_LAYER_READY:
            # Lotería estricta: 50/50. Solo el ganador intenta; si no tiene espacio, no se intenta el otro.
            winner_is_A = (random.randint(1, 100) <= 50)
            sent = False

            if winner_is_A:
                if A.tx_window_has_space():
                    A.tx_push_new(epoch); sent = True
                    if ack_owner == "A":
                        try: stop_ack_timer()
                        except Exception: pass
                        ack_owner = None
                    pb_ready += 1
            else:
                if B.tx_window_has_space():
                    B.tx_push_new(epoch); sent = True
                    if ack_owner == "B":
                        try: stop_ack_timer()
                        except Exception: pass
                        ack_owner = None
                    pb_ready += 1

            # Rearme de READY:
            # - Si nadie envió y queda espacio en alguno → rearmar (el otro perdió la lotería).
            # - Si alguien envió y aún queda espacio en alguno → rearmar para seguir drenando.
            # - Si ambos sin espacio → esperar ACK/timeout.
            if want_app_ready():
                rearm_ready()

        elif ev == EventType.FRAME_ARRIVAL:
            r = from_physical_layer(payload)
            if not r:
                processed += 1; epoch += 1
                continue

            if r.kind == FrameKind.DATA:
                data = r.info.data

                if data.startswith("A>"):
                    # RX en B (flujo A->B)
                    B.rx_handle_data(r.seq, r.info)
                    # Consumir ACK piggyback (confirma B->A) que venía en ese DATA
                    B.tx_consume_ack(r.ack)

                    # ACK diferido: si no piggybackeamos pronto, saldrá ACK puro
                    try: stop_ack_timer()
                    except Exception: pass
                    start_ack_timer(); ack_owner = "B"

                elif data.startswith("B>"):
                    # RX en A (flujo B->A)
                    A.rx_handle_data(r.seq, r.info)
                    A.tx_consume_ack(r.ack)

                    try: stop_ack_timer()
                    except Exception: pass
                    start_ack_timer(); ack_owner = "A"

                # SIN piggyback oportunista: NO se envía DATA aquí.
                # Si ahora hay espacio para que la app empuje, rearmar READY.
                if want_app_ready():
                    rearm_ready()

            elif r.kind == FrameKind.ACK:
                tag = r.info.data
                if tag == "ACK:A":
                    B.tx_consume_ack(r.ack)
                elif tag == "ACK:B":
                    A.tx_consume_ack(r.ack)

                # Si se liberó espacio, rearmar READY para que la app empuje.
                if want_app_ready():
                    rearm_ready()

        elif ev == EventType.ACK_TIMEOUT:
            # Dispara ACK puro del dueño si no alcanzó a piggybackear
            if ack_owner == "A":
                ack_seq = A.ack_pending_seq if A.ack_pending_seq is not None else A.last_in_order()
                to_physical_layer(Frame(FrameKind.ACK, 0, ack_seq, Packet("ACK:A")))
                A.ack_pending_seq = None
                ack_owner = None
                ack_pure += 1
            elif ack_owner == "B":
                ack_seq = B.ack_pending_seq if B.ack_pending_seq is not None else B.last_in_order()
                to_physical_layer(Frame(FrameKind.ACK, 0, ack_seq, Packet("ACK:B")))
                B.ack_pending_seq = None
                ack_owner = None
                ack_pure += 1

            # Tras ACK puro, si hay espacio en alguno, rearmar READY
            if want_app_ready():
                rearm_ready()

        elif ev == EventType.TIMEOUT:
            # Retransmisión de DATA en vuelo (SW: la base)
            key = payload  # OFFSET+seq
            if key >= OFFSET_B:
                B.tx_timeout(key, epoch)
            else:
                A.tx_timeout(key, epoch)

            # SW sigue esperando, pero el otro lado podría tener espacio
            if want_app_ready():
                rearm_ready()

        processed += 1
        epoch += 1

    # (Opcional) métricas
    # print(f"Piggyback READY: {pb_ready} | ACK puros: {ack_pure}")