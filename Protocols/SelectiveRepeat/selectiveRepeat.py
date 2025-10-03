from Utils.types import Frame, FrameKind, EventType, Packet
from Utils.util import inc, between
from Events.api import (
    wait_for_event, from_network_layer, to_physical_layer, from_physical_layer,
    to_network_layer, start_timer, stop_timer, start_ack_timer, stop_ack_timer,
    enable_network_layer, disable_network_layer
)
import random  # sorteo 50/50

OFFSET_A = 0
OFFSET_B = 100

class SRPeerUni:
    """
    Un extremo Selective Repeat (estado TX/RX) con:
      - Ventana SR, timers por trama (offset A/B),
      - RX con arrived[]/in_buf[] y entrega en orden,
      - ACK ACUMULATIVO en DATA (piggyback = last_in_order()),
      - Retransmisión SELECTIVA por TIMEOUT,
      - De-dupe por epoch para DATA y reducción de ACK puros duplicados,
      - Señal 'ack_due' para controlar si debemos un ACK puro.
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

        # De-dupe por epoch (para DATA)
        self._last_sent_epoch = {}  # seq -> epoch

        # Señal para ACK diferido (puro) + de-dupe de ACK puro
        self.ack_due = False              # debemos un ACK puro (si no piggybackeamos pronto)
        self._last_ack_value = None       # último valor de ACK puro enviado
        self._last_ack_epoch = None       # epoch del último ACK puro enviado

    # -------- TX helpers --------
    def tx_window_has_space(self) -> bool:
        return len(self.out_buf) < self.nr_bufs

    def tx_offset(self) -> int:
        return OFFSET_A if self.label == "A" else OFFSET_B

    def last_in_order(self) -> int:
        """ACK acumulativo = último en orden entregado = frame_expected - 1 (mod M)."""
        return (self.frame_expected + self.max_seq) % (self.max_seq + 1)

    def _should_skip_send_this_epoch(self, seq: int, epoch: int) -> bool:
        return self._last_sent_epoch.get(seq) == epoch

    def _mark_sent_epoch(self, seq: int, epoch: int):
        self._last_sent_epoch[seq] = epoch

    def tx_send_data(self, epoch: int):
        """
        Envía DATA con piggyback ACUMULATIVO (last_in_order()).
        Si piggybackeamos, ya no debemos ACK puro → ack_due = False.
        """
        s = self.next_to_send
        if self._should_skip_send_this_epoch(s, epoch):
            return

        p = from_network_layer()
        p_labeled = Packet(f"{self.label}>{p.data}")

        self.out_buf[s] = p_labeled
        ack_pb = self.last_in_order()  # SIEMPRE acumulativo
        to_physical_layer(Frame(FrameKind.DATA, s, ack_pb, p_labeled))
        self._mark_sent_epoch(s, epoch)
        start_timer(self.tx_offset() + s)
        self.next_to_send = inc(s, self.max_seq)

        # Piggyback realizado → ya no debemos ACK puro
        self.ack_due = False

    def tx_ack_one(self, a: int):
        """
        Trata 'a' como ACK ACUMULATIVO:
          - Si 'a' está dentro de la ventana [base, base+nr_bufs), confirma TODAS
            las tramas desde 'base' hasta 'a' (inclusive) en aritmética modular.
          - Si no cae en la ventana, lo ignora (ACK tardío o fuera de rango).
        """
        if not self.out_buf:
            return

        M = self.max_seq + 1
        base = (self.next_to_send - len(self.out_buf)) % M
        too_far = (base + self.nr_bufs) % M

        if between(base, a, too_far):
            cur = base
            stop_at = inc(a, self.max_seq)
            while cur != stop_at:
                if cur in self.out_buf:
                    try:
                        stop_timer(self.tx_offset() + cur)
                    except Exception:
                        pass
                    self.out_buf.pop(cur, None)
                cur = inc(cur, self.max_seq)
        # else: fuera de ventana → ignorar

    def tx_retransmit_one(self, seq: int, epoch: int):
        """
        Retransmisión SELECTIVA de 'seq' si sigue pendiente.
        Piggyback acumulativo también en la retransmisión.
        """
        if seq in self.out_buf:
            if self._should_skip_send_this_epoch(seq, epoch):
                return
            ack_pb = self.last_in_order()
            to_physical_layer(Frame(FrameKind.DATA, seq, ack_pb, self.out_buf[seq]))
            self._mark_sent_epoch(seq, epoch)
            start_timer(self.tx_offset() + seq)
            # Piggyback → no debemos ACK puro
            self.ack_due = False

    # -------- RX helpers --------
    def rx_accept_and_deliver(self, r_seq: int, info: Packet):
        """
        Acepta dentro de [frame_expected, too_far), bufferiza y entrega en orden.
        Marca ack_due=True (debemos un ACK) y avanza frame_expected/too_far.
        """
        # Cada DATA recibido hace que debamos un ACK (si no piggybackeamos)
        self.ack_due = True

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
#     DISPATCHER BIDIRECCIONAL (Burst-K, scheduler LOTERÍA ESTRICTA)
# =====================================================================

def run_sr_bidirectional(steps=1000, max_seq=7, burst_k=None, rng_seed=None):
    """
    - Piggyback SIEMPRE acumulativo (last_in_order()) en DATA.
    - ACK puro (diferido) también acumulativo en ACK_TIMEOUT, con de-dupe.
    - Retransmisión selectiva en TIMEOUT por trama.
    - Lotería estricta: por cada NETWORK_LAYER_READY, sorteo 50/50 (A/B).
      * SOLO el ganador intenta enviar; si no tiene espacio, NO se intenta el otro.
      * Para progreso, si alguno tiene espacio, la red queda habilitada.
    - Burst-K: el ganador envía hasta K (o hasta llenar su ventana) en ese evento.
    """
    if rng_seed is not None:
        random.seed(rng_seed)

    A = SRPeerUni("A", max_seq=max_seq)
    B = SRPeerUni("B", max_seq=max_seq)

    if burst_k is None:
        burst_k = A.nr_bufs  # por defecto, tamaño de ventana

    enable_network_layer()

    processed = 0
    epoch = 0

    def burst_send(peer: SRPeerUni, epoch_val: int) -> int:
        free_space = peer.nr_bufs - len(peer.out_buf)
        if free_space <= 0:
            return 0
        budget = min(burst_k, free_space)
        sent_here = 0

        # Si este lado debía un ACK puro, al piggybackear lo vamos a saldar
        #  → No hace falta tocar timers aquí; el scheduler de ACK puro
        #    se controla en FRAME_ARRIVAL / ACK_TIMEOUT.
        for _ in range(budget):
            if not peer.tx_window_has_space():
                break
            peer.tx_send_data(epoch_val)
            sent_here += 1
        return sent_here

    while processed < steps:
        ev, payload = wait_for_event()

        if ev == EventType.NETWORK_LAYER_READY:
            sent_total = 0

            winner_is_A = (random.randint(1, 100) <= 50)
            if winner_is_A:
                if A.tx_window_has_space():
                    # Vamos a piggybackear: si había ack_timer activo, se puede cancelar
                    # (lo cancela el motor de eventos; aquí no tenemos handler directo del timer)
                    sent_total += burst_send(A, epoch)
            else:
                if B.tx_window_has_space():
                    sent_total += burst_send(B, epoch)

            # Política de red
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
                processed += 1; epoch += 1
                continue

            if r.kind == FrameKind.DATA:
                data = r.info.data
                if r.kind == FrameKind.DATA:
                    data = r.info.data
                    if data.startswith("A>"):
                        # RX en B (A->B) — pasa el Packet tal cual
                        B.rx_accept_and_deliver(r.seq, r.info)
                        B.tx_ack_one(r.ack)
                        try:
                            stop_ack_timer()
                        except Exception:
                            pass
                        start_ack_timer()
                        ack_owner = "B"
                        enable_network_layer()

                    elif data.startswith("B>"):
                        # RX en A (B->A) — pasa el Packet tal cual
                        A.rx_accept_and_deliver(r.seq, r.info)
                        A.tx_ack_one(r.ack)
                        try:
                            stop_ack_timer()
                        except Exception:
                            pass
                        start_ack_timer()
                        ack_owner = "A"
                        enable_network_layer()
            elif r.kind == FrameKind.ACK:
                tag = r.info.data
                if tag == "ACK:A":
                    B.tx_ack_one(r.ack)  # acumulativo
                    enable_network_layer()
                elif tag == "ACK:B":
                    A.tx_ack_one(r.ack)  # acumulativo
                    enable_network_layer()

        elif ev == EventType.ACK_TIMEOUT:
            # ACK puro acumulativo con de-dupe: solo si "debemos" ACK
            # y evitando repetir el mismo valor dentro del mismo epoch
            a_ack = A.last_in_order()
            b_ack = B.last_in_order()

            # ¿A debe ACK?
            if A.ack_due:
                if not (A._last_ack_epoch == epoch and A._last_ack_value == a_ack):
                    to_physical_layer(Frame(FrameKind.ACK, 0, a_ack, Packet("ACK:A")))
                    A._last_ack_value = a_ack
                    A._last_ack_epoch = epoch
                A.ack_due = False  # ya saldado

            # ¿B debe ACK?
            if B.ack_due:
                if not (B._last_ack_epoch == epoch and B._last_ack_value == b_ack):
                    to_physical_layer(Frame(FrameKind.ACK, 0, b_ack, Packet("ACK:B")))
                    B._last_ack_value = b_ack
                    B._last_ack_epoch = epoch
                B.ack_due = False

            enable_network_layer()

        elif ev == EventType.TIMEOUT:
            # Retransmisión selectiva (si sigue pendiente)
            key = payload  # offset+seq
            if key >= OFFSET_B:
                B.tx_retransmit_one(key - OFFSET_B, epoch)
            else:
                A.tx_retransmit_one(key - OFFSET_A, epoch)
            enable_network_layer()

        processed += 1
        epoch += 1