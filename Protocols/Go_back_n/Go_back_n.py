# Protocols/Go_back_n/Go_back_n.py — GBN clásico (sin piggyback oportunista, timer único en base)
from Utils.types import Frame, FrameKind, EventType, Packet
from Utils.util import inc, between
from Events.api import (
    wait_for_event, from_network_layer, to_physical_layer, from_physical_layer,
    to_network_layer, start_timer, stop_timer, start_ack_timer, stop_ack_timer,
    enable_network_layer, disable_network_layer
)
import random  # lotería 50/50

OFFSET_A = 0
OFFSET_B = 100


class GBNPeer:
    """
    Go-Back-N 'fiel':
      - Ventana = max_seq (máx outstanding).
      - RX entrega SOLO en orden (descarta dup/adelantadas).
      - ACK acumulativo (piggyback en DATA; ACK puro diferido).
      - Timer ÚNICO: solo para la trama 'base' (ack_expected).
      - Cualquier TIMEOUT => reenvío de TODAS las outstanding desde base.
      - De-duplicación por 'epoch' para evitar doble envío en el mismo tick.
    """
    def __init__(self, label: str, max_seq: int = 7):
        assert label in ("A", "B")
        self.label = label
        self.max_seq = max_seq
        self.window = max_seq          # tamaño de ventana GBN (máx outstanding)

        # ----- TX -----
        self.ack_expected = 0          # base (primera no ACKeada)
        self.next_to_send = 0          # siguiente seq libre
        self.nbuffered = 0             # outstanding count
        self.out_buf = {}              # seq -> Packet

        # ----- RX -----
        self.frame_expected = 0        # SOLO acepta esta; dup/adelantadas se ignoran

        # ----- De-dupe por epoch -----
        self._last_sent_epoch = {}     # seq -> epoch

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
        Saca paquete de app, etiqueta 'A>'/'B>', lo guarda en out_buf[next_to_send],
        envía DATA con piggyback acumulativo y (si es la base) arranca el timer único.
        """
        p = from_network_layer()
        p_labeled = Packet(f"{self.label}>{p.data}")
        s = self.next_to_send

        self.out_buf[s] = p_labeled
        self.nbuffered += 1
        self._send_data(s, epoch)              # arranca timer SOLO si s == ack_expected
        self.next_to_send = inc(s, self.max_seq)

    def _send_data(self, seq: int, epoch: int):
        """
        Envía DATA(seq) con piggyback (ACK acumulativo = last_in_order()).
        De-dupe: no duplica en el mismo epoch. Timer ÚNICO: solo para la base.
        """
        if self._should_skip_send_this_epoch(seq, epoch):
            return
        ack_pb = self.last_in_order()
        to_physical_layer(Frame(FrameKind.DATA, seq, ack_pb, self.out_buf[seq]))
        self._mark_sent_epoch(seq, epoch)

        # === Timer ÚNICO (GBN clásico): solo para la base ===
        if seq == self.ack_expected:
            start_timer(self.tx_offset() + seq)

    def tx_consume_ack(self, a: int):
        """
        Procesa ACK acumulativo (puro o piggyback). Avanza base mientras
        ack_expected <= a < next_to_send (aritmética modular).
        Manejo del timer único: se detiene el de la base vieja y se (re)inicia
        para la nueva base si aún hay outstanding.
        """
        advanced = False
        while (self.nbuffered > 0) and between(self.ack_expected, a, self.next_to_send):
            old_base = self.ack_expected
            # El timer activo (si existe) es el de old_base: detenlo
            try:
                stop_timer(self.tx_offset() + old_base)
            except Exception:
                pass

            # Libera la trama confirmada y avanza
            self.out_buf.pop(old_base, None)
            self.nbuffered -= 1
            self.ack_expected = inc(self.ack_expected, self.max_seq)
            advanced = True

        # Si aún queda pendiente, (re)arranca timer para la nueva base
        if advanced and self.nbuffered > 0:
            try:
                start_timer(self.tx_offset() + self.ack_expected)
            except Exception:
                pass

    def tx_timeout(self, _timed_seq: int, epoch: int):
        """
        ANY TIMEOUT (de la base) ⇒ reenvío de TODAS las outstanding desde base.
        El timer se volverá a activar solo para la base por _send_data().
        """
        if self.nbuffered == 0:
            return
        s = self.ack_expected
        for _ in range(self.nbuffered):
            self._send_data(s, epoch)  # solo la base re-arma timer
            s = inc(s, self.max_seq)

    # -------------------- RX core --------------------
    def rx_handle_data(self, r_seq: int, info: Packet):
        """
        GBN clásico: entrega SÓLO si r_seq == frame_expected. Duplicados y
        adelantadas se ignoran (pero se responderá con ACK acumulativo).
        """
        if r_seq == self.frame_expected:
            to_network_layer(info)
            self.frame_expected = inc(self.frame_expected, self.max_seq)


# =====================================================================
#                   DISPATCHER BIDIRECCIONAL (GBN)
#   - Lotería estricta 50/50 por NETWORK_LAYER_READY (como en SR).
#   - SIN piggyback oportunista (no se envía DATA en FRAME_ARRIVAL).
#   - ACK puro diferido con un solo ack_timer y 'ack_owner'.
#   - Timer ÚNICO por lado (solo base). TIMEOUT => reenvía TODAS desde base.
#   - De-dupe por epoch para no duplicar envíos en un mismo tick.
#   - Si tu Engine tiene ready_on_enable=True, cada enable() agenda un READY.
# =====================================================================

def run_gbn_bidirectional(steps=2000, max_seq=7, burst_k=None, rng_seed=None):
    if rng_seed is not None:
        random.seed(rng_seed)

    A = GBNPeer("A", max_seq=max_seq)
    B = GBNPeer("B", max_seq=max_seq)

    # Tamaño de ráfaga por defecto: tamaño de ventana (puedes pasar burst_k=1 si quieres menos reordenamiento)
    if burst_k is None:
        burst_k = A.window

    enable_network_layer()

    processed = 0
    epoch = 0
    ack_owner = None  # "A" si A debe ACK puro; "B" si B debe ACK puro

    def burst_send(peer: GBNPeer, epoch_val: int) -> int:
        """
        Envío en ráfaga hasta 'burst_k' o hasta llenar ventana.
        Si este peer debía ACK puro, al piggybackear lo cancela (se para ack_timer).
        """
        nonlocal ack_owner

        free = peer.window - peer.nbuffered
        if free <= 0:
            return 0
        budget = min(burst_k, free)
        sent = 0
        for _ in range(budget):
            peer.tx_push_new(epoch_val)
            sent += 1

            # Si piggybackeó y era dueño del ACK diferido, cancelamos ese ack_timer
            if (peer.label == "A" and ack_owner == "A") or (peer.label == "B" and ack_owner == "B"):
                try:
                    stop_ack_timer()
                except Exception:
                    pass
                ack_owner = None
        return sent

    while processed < steps:
        ev, payload = wait_for_event()

        if ev == EventType.NETWORK_LAYER_READY:
            sent_total = 0
            # Lotería estricta: 50/50 entre A y B
            winner_is_A = (random.randint(1, 100) <= 50)

            if winner_is_A:
                if A.tx_window_has_space():
                    sent_total += burst_send(A, epoch)
            else:
                if B.tx_window_has_space():
                    sent_total += burst_send(B, epoch)

            # Política de red (idéntica a SR):
            # - Si nadie envió y ambas ventanas llenas -> deshabilita red.
            # - En caso contrario -> habilita (y con ready_on_enable se agenda READY).
            if sent_total == 0:
                if (not A.tx_window_has_space()) and (not B.tx_window_has_space()):
                    disable_network_layer()
                else:
                    enable_network_layer()
            else:
                enable_network_layer()

        elif ev == EventType.FRAME_ARRIVAL:
            r = from_physical_layer(payload)
            if not r:
                processed += 1
                epoch += 1
                continue

            if r.kind == FrameKind.DATA:
                data = r.info.data

                if data.startswith("A>"):
                    # RX en B (flujo A->B)
                    B.rx_handle_data(r.seq, r.info)
                    # Consumir ACK acumulativo piggyback (confirma B->A)
                    B.tx_consume_ack(r.ack)

                    # Delayed-ACK: si no piggybackeamos pronto, enviaremos ACK puro
                    try:
                        stop_ack_timer()
                    except Exception:
                        pass
                    start_ack_timer()
                    ack_owner = "B"

                elif data.startswith("B>"):
                    # RX en A (flujo B->A)
                    A.rx_handle_data(r.seq, r.info)
                    A.tx_consume_ack(r.ack)

                    try:
                        stop_ack_timer()
                    except Exception:
                        pass
                    start_ack_timer()
                    ack_owner = "A"

                # SIN piggyback oportunista: aquí NO se envía DATA.
                # Solo re-habilitamos la app si hay espacio en alguna ventana.
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
            # ACK puro acumulativo del dueño actual
            if ack_owner == "A":
                to_physical_layer(Frame(FrameKind.ACK, 0, A.last_in_order(), Packet("ACK:A")))
                ack_owner = None
            elif ack_owner == "B":
                to_physical_layer(Frame(FrameKind.ACK, 0, B.last_in_order(), Packet("ACK:B")))
                ack_owner = None
            enable_network_layer()

        elif ev == EventType.TIMEOUT:
            # Timer único por lado ⇒ TIMEOUT debe corresponder a la base de ese lado.
            key = payload  # offset + seq
            if key >= OFFSET_B:
                B.tx_timeout(key - OFFSET_B, epoch)  # reenvía TODAS desde base (GBN)
                if ack_owner == "B":
                    try:
                        stop_ack_timer()
                    except Exception:
                        pass
                    ack_owner = None
            else:
                A.tx_timeout(key - OFFSET_A, epoch)
                if ack_owner == "A":
                    try:
                        stop_ack_timer()
                    except Exception:
                        pass
                    ack_owner = None
            enable_network_layer()

        processed += 1
        epoch += 1