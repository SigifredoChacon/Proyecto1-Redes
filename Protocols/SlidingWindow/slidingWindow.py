# Protocols/SlidingWindow/slidingWindow.py
# Stop-and-Wait (ventana=1) full-duplex con piggyback + ACK diferido,
# compatible con tu Engine y el esquema de SR (enable/disable, start_ack_timer, etc.)

from Utils.types import Frame, FrameKind, EventType, Packet
from Utils.util import inc
from Events.api import (
    wait_for_event, from_network_layer, to_physical_layer, from_physical_layer,
    to_network_layer, start_timer, stop_timer, start_ack_timer, stop_ack_timer,
    enable_network_layer, disable_network_layer
)

# Offsets de timers para separar A y B en el Engine global
OFFSET_A = 0
OFFSET_B = 100

class SW1Peer:
    """
    Stop-and-Wait full-duplex (W=1) con:
      - timers de DATA por peer (usando offsets),
      - piggyback oportunista,
      - ACK diferido con start_ack_timer/stop_ack_timer,
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
        self.ack_pending_seq = None  # último DATA recibido correctamente

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
        """Saca de la network layer, etiqueta y envía DATA con piggyback."""
        s = self.seq
        if self._should_skip_send_this_epoch(s, epoch):
            return  # de-dupe intra-tick

        p = from_network_layer()
        p_labeled = Packet(f"{self.label}>{p.data}")
        self.out_buf[s] = p_labeled

        ack_pb = self.ack_pending_seq if self.ack_pending_seq is not None else self.last_in_order()
        to_physical_layer(Frame(FrameKind.DATA, s, ack_pb, p_labeled))
        self._mark_sent_epoch(s, epoch)
        start_timer(self.tx_offset() + s)

        self.waiting = True
        self.ack_expected = s
        # limpia el pendiente (ya piggybackeado)
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
            to_network_layer(info)
            self.frame_expected ^= 1
        # En cualquier caso, el ACK selectivo debido al emisor es el último correcto recibido
        self.ack_pending_seq = r_seq  # para SW coincide con acumulativo (último correcto)

# =========================================================
#                  BUCLE BIDIRECCIONAL
# =========================================================

def run_gbn_bidirectional(steps=2000, max_seq=1):
    """
    Stop-and-Wait (W=1) full-duplex con:
      - Piggyback oportunista,
      - ACK diferido (único timer compartido del engine),
      - Timers de DATA por peer usando offsets,
      - De-dupe por epoch,
      - Gating de la network layer para evitar doble envío en el mismo instante.
    """
    A = SW1Peer("A")
    B = SW1Peer("B")

    enable_network_layer()
    processed = 0
    epoch = 0                # contador de ticks/iteraciones
    turn = 0                 # para arbitrar NETWORK_LAYER_READY entre A y B
    ack_owner = None         # None | "A" | "B"

    # Métricas opcionales (te ayudan a ver el comportamiento)
    pb_ready = 0             # piggyback al atender READY natural
    pb_opp   = 0             # piggyback oportunista tras FRAME_ARRIVAL
    ack_pure = 0             # ACK puros por ACK_TIMEOUT

    while processed < steps:
        ev, payload = wait_for_event()
        did_send_now = False

        if ev == EventType.NETWORK_LAYER_READY:
            # Intentamos dar servicio una sola vez por iteración (A xor B)
            if turn % 2 == 0:
                if A.tx_window_has_space():
                    A.tx_push_new(epoch); did_send_now = True
                    # Si A piggybackeó, cancelamos cualquier ack diferido de A
                    if ack_owner == "A":
                        try: stop_ack_timer()
                        except Exception: pass
                        ack_owner = None
                    pb_ready += 1
                elif B.tx_window_has_space():
                    B.tx_push_new(epoch); did_send_now = True
                    if ack_owner == "B":
                        try: stop_ack_timer()
                        except Exception: pass
                        ack_owner = None
                    pb_ready += 1
                else:
                    disable_network_layer()
            else:
                if B.tx_window_has_space():
                    B.tx_push_new(epoch); did_send_now = True
                    if ack_owner == "B":
                        try: stop_ack_timer()
                        except Exception: pass
                        ack_owner = None
                    pb_ready += 1
                elif A.tx_window_has_space():
                    A.tx_push_new(epoch); did_send_now = True
                    if ack_owner == "A":
                        try: stop_ack_timer()
                        except Exception: pass
                        ack_owner = None
                    pb_ready += 1
                else:
                    disable_network_layer()

            turn += 1
            # Si ya enviamos algo, cortamos la iteración para no duplicar
            if did_send_now:
                # Importante: cerrar la red para que el siguiente envío sea en otro tick
                disable_network_layer()
                processed += 1; epoch += 1
                continue

            # Si no enviamos nada pero hay espacio en alguno, deja abierta la red
            if A.tx_window_has_space() or B.tx_window_has_space():
                enable_network_layer()
            else:
                disable_network_layer()

        elif ev == EventType.FRAME_ARRIVAL:
            r = from_physical_layer(payload)
            if not r:
                processed += 1; epoch += 1
                continue

            if r.kind == FrameKind.DATA:
                data = r.info.data

                if data.startswith("A>"):
                    # Llegó DATA A->B
                    B.rx_handle_data(r.seq, Packet(data[2:]))

                    # Consumir ACK piggyback que confirma B->A
                    B.tx_consume_ack(r.ack)

                    # Piggyback oportunista: si B puede, que envíe ya
                    try: stop_ack_timer()
                    except Exception: pass
                    ack_owner = None
                    if B.tx_window_has_space():
                        B.tx_push_new(epoch)
                        did_send_now = True
                        pb_opp += 1
                    else:
                        # No hay espacio ahora: diferimos ACK puro
                        start_ack_timer(); ack_owner = "B"

                elif data.startswith("B>"):
                    # Llegó DATA B->A
                    A.rx_handle_data(r.seq, Packet(data[2:]))

                    # Consumir ACK piggyback que confirma A->B
                    A.tx_consume_ack(r.ack)

                    # Piggyback oportunista: si A puede, que envíe ya
                    try: stop_ack_timer()
                    except Exception: pass
                    ack_owner = None
                    if A.tx_window_has_space():
                        A.tx_push_new(epoch)
                        did_send_now = True
                        pb_opp += 1
                    else:
                        start_ack_timer(); ack_owner = "A"

                # Tras un envío oportunista, corta para no duplicar en el mismo tick
                if did_send_now:
                    disable_network_layer()
                    processed += 1; epoch += 1
                    continue

                # Si no se envió nada, decide si la red queda abierta (por si hay hueco)
                if A.tx_window_has_space() or B.tx_window_has_space():
                    enable_network_layer()
                else:
                    disable_network_layer()

            elif r.kind == FrameKind.ACK:
                tag = r.info.data
                if tag == "ACK:A":
                    B.tx_consume_ack(r.ack)
                elif tag == "ACK:B":
                    A.tx_consume_ack(r.ack)

                # Si consumimos ack, puede que ahora haya hueco; deja la red abierta
                if A.tx_window_has_space() or B.tx_window_has_space():
                    enable_network_layer()
                else:
                    disable_network_layer()

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

            # Tras un ACK puro, no fuerces otro envío en este mismo tick
            disable_network_layer()

        elif ev == EventType.TIMEOUT:
            # Retransmisión de DATA en vuelo (SW: la base)
            key = payload  # OFFSET+seq
            if key >= OFFSET_B:
                B.tx_timeout(key, epoch)
            else:
                A.tx_timeout(key, epoch)

            # Tras retransmitir, corta para no duplicar
            disable_network_layer()

        processed += 1
        epoch += 1

    # (Opcional) estadísticas de piggyback/ACK
    print(f"Piggyback READY: {pb_ready} | Piggyback oportunista: {pb_opp} | ACK puros: {ack_pure}")