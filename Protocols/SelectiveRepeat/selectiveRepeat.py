from Utils.types import Frame, FrameKind, EventType, Packet
from Utils.util import inc, between
from Events.api import (
    wait_for_event, from_network_layer, to_physical_layer, from_physical_layer,
    to_network_layer, start_timer, stop_timer, start_ack_timer, stop_ack_timer,
    enable_network_layer, disable_network_layer
)
import random

OFFSET_A = 0
OFFSET_B = 100

class SRPeerUni:

    def __init__(self, label, max_seq = 7):
        assert label in ("A", "B")
        self.label = label
        self.max_seq = max_seq
        self.nr_bufs = (max_seq + 1) // 2

        # ----- Estado TX -----
        self.next_to_send = 0
        self.out_buf = {} #Los que faltan por que sean confirmadas

        # ----- Estado RX -----
        self.frame_expected = 0
        self.too_far = self.nr_bufs
        self.arrived = [False] * self.nr_bufs
        self.in_buf = [None] * self.nr_bufs


        self._last_sent_epoch = {}


        self.ack_due = False
        self._last_ack_value = None
        self._last_ack_epoch = None

    # -------- TX helpers --------
    """
        Funcion que verifica si hay espacio en la ventana de transmision
        Args:
            (ninguno): Usa self.out_buf (dict/buffer de frames pendientes) y self.nr_bufs (tamano de ventana)
        Returns:
            bool: True si el emisor puede enviar otro frame (len(out_buf) < nr_bufs), False en caso contrario
    """
    def tx_window_has_space(self):
        return len(self.out_buf) < self.nr_bufs


    """
        Funcion que obtiene la base de temporizadores/ids segun el lado
        Args:
            (ninguno): Usa self.label ("A" o "B") para decidir el offset
        Returns:
            int: OFFSET_A si label es "A", de lo contrario OFFSET_B
    """
    def tx_offset(self):
        return OFFSET_A if self.label == "A" else OFFSET_B

    """
        Funcion que calcula el ultimo numero recibido en orden contiguo (ACK acumulativo)
        Args:
            (ninguno): Usa self.frame_expected (siguiente en orden) y self.max_seq (maximo valor de secuencia)
        Returns:
            int: El numero de secuencia inmediatamente anterior a frame_expected, en modulo (max_seq+1)
    """
    def last_in_order(self):
        return (self.frame_expected + self.max_seq) % (self.max_seq + 1)

    """
        Funcion que decide si debe omitirse el envio de un seq en este epoch
        Args:
            seq (int): Numero de secuencia a evaluar
            epoch (int): Identificador de la iteracion/epoch actual de envio
        Returns:
            bool: True si ya se envio este seq en el epoch dado (evitar duplicados en el mismo ciclo), False si puede enviarse
    """
    def _should_skip_send_this_epoch(self, seq, epoch):
        return self._last_sent_epoch.get(seq) == epoch

    """
        Funcion que marca que un numero de secuencia fue enviado en un epoch especifico
        Args:
            seq (int): Numero de secuencia enviado
            epoch (int): Identificador del epoch en el que se envio
        Returns:
            None: Actualiza el registro interno self._last_sent_epoch con la pareja (seq, epoch)
    """
    def _mark_sent_epoch(self, seq, epoch):
        self._last_sent_epoch[seq] = epoch


    """
        Funcion que envia un frame de datos con piggyback de ACK acumulativo
        Args:
            epoch (int): Identificador de la iteracion/epoch de envio para evitar reenviar el mismo seq en el mismo ciclo
        Returns:
            None: Toma un paquete de la capa de red, lo etiqueta, arma y envia un DATA(s, ack_pb),
                  arranca el temporizador de s, avanza next_to_send y limpia la marca de ACK pendiente (ack_due=False)
    """
    def tx_send_data(self, epoch):

        s = self.next_to_send
        if self._should_skip_send_this_epoch(s, epoch):
            return

        p = from_network_layer()
        p_labeled = Packet(f"{self.label}>{p.data}")

        self.out_buf[s] = p_labeled
        ack_pb = self.last_in_order()
        to_physical_layer(Frame(FrameKind.DATA, s, ack_pb, p_labeled))
        self._mark_sent_epoch(s, epoch)
        start_timer(self.tx_offset() + s)
        self.next_to_send = inc(s, self.max_seq)


        self.ack_due = False

    """
        Funcion que procesa un ACK acumulativo y limpia el buffer de salida
        Args:
            a (int): Numero de secuencia confirmado acumulativamente (confirma todo hasta 'a' inclusive)
        Returns:
            None: Si 'a' cae dentro de la ventana activa, detiene timers y elimina de out_buf
                  todos los frames desde la base hasta 'a' (inclusive)
    """
    def tx_ack_one(self, a):

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

    """
        Funcion que retransmite un frame de datos especifico con piggyback de ACK acumulativo
        Args:
            seq (int): Numero de secuencia a retransmitir
            epoch (int): Identificador del ciclo/epoch actual para evitar multiples envios en el mismo epoch
        Returns:
            None: Si el seq sigue pendiente en out_buf, reenvia DATA(seq, ack_pb, payload),
                  marca el epoch, reinicia el temporizador de seq y limpia ack pendiente (ack_due=False)
    """
    def tx_retransmit_one(self, seq, epoch):

        if seq in self.out_buf:
            if self._should_skip_send_this_epoch(seq, epoch):
                return
            ack_pb = self.last_in_order()
            to_physical_layer(Frame(FrameKind.DATA, seq, ack_pb, self.out_buf[seq]))
            self._mark_sent_epoch(seq, epoch)
            start_timer(self.tx_offset() + seq)

            self.ack_due = False

    # -------- RX helpers --------

    """
        Funcion que acepta un frame recibido y lo entrega o lo bufferiza
        Args:
            r_seq (int): Numero de secuencia del frame recibido
            info (Packet): Paquete de datos contenido en el frame
        Returns:
            None: Marca ACK pendiente, guarda en buffer si esta dentro de la ventana y aun no habia llegado,
                  entrega en orden continuo a la capa de red y avanza la ventana (frame_expected y too_far)
    """
    def rx_accept_and_deliver(self, r_seq, info):

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




"""
    Funcion que ejecuta el protocolo Selective Repeat bidireccional con envios en rafaga
    Args:
        steps (int): Numero maximo de eventos a procesar por el motor de simulacion
        max_seq (int): Maximo numero de secuencia (el espacio es de 0..max_seq, modulo max_seq+1)
        burst_k (int): Limite superior de envios por rafaga cuando hay espacio en la ventana;
                                 si es None, se usa el tamano de la ventana (nr_bufs) del emisor
        rng_seed (int): Semilla para el generador pseudoaleatorio (reproducibilidad)
    Returns:
        None: Inicializa dos extremos SR (A y B) y ejecuta el bucle de eventos;
              en NETWORK_LAYER_READY realiza rafagas hasta agotar ventana;
              en FRAME_ARRIVAL entrega/bufferiza datos, hace ACK acumulativo (piggyback o ACK puro);
              en ACK_TIMEOUT emite ACKs puros diferidos; en TIMEOUT retransmite un solo frame.
"""
def run_sr_bidirectional(steps=1000, max_seq=7, burst_k=None, rng_seed=None):

    if rng_seed is not None:
        random.seed(rng_seed)

    A = SRPeerUni("A", max_seq=max_seq)
    B = SRPeerUni("B", max_seq=max_seq)

    if burst_k is None:
        burst_k = A.nr_bufs

    enable_network_layer()

    processed = 0
    epoch = 0

    """
        Funcion que envia una rafaga de DATA respetando el espacio de la ventana
        Args:
            peer (SRPeerUni): Extremo SR que realiza los envios (usa nr_bufs y out_buf)
            epoch_val (int): Identificador del epoch/ciclo actual para marcar envios y evitar duplicados
        Returns:
            int: Cantidad de frames DATA efectivamente enviados en esta rafaga
    """
    def burst_send(peer, epoch_val):
        free_space = peer.nr_bufs - len(peer.out_buf)
        if free_space <= 0:
            return 0
        budget = min(burst_k, free_space)
        sent_here = 0

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

                    sent_total += burst_send(A, epoch)
            else:
                if B.tx_window_has_space():
                    sent_total += burst_send(B, epoch)


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
                    B.tx_ack_one(r.ack)
                    enable_network_layer()
                elif tag == "ACK:B":
                    A.tx_ack_one(r.ack)
                    enable_network_layer()

        elif ev == EventType.ACK_TIMEOUT:

            a_ack = A.last_in_order()
            b_ack = B.last_in_order()

            # ¿A debe ACK?
            if A.ack_due:
                if not (A._last_ack_epoch == epoch and A._last_ack_value == a_ack):
                    to_physical_layer(Frame(FrameKind.ACK, 0, a_ack, Packet("ACK:A")))
                    A._last_ack_value = a_ack
                    A._last_ack_epoch = epoch
                A.ack_due = False

            # ¿B debe ACK?
            if B.ack_due:
                if not (B._last_ack_epoch == epoch and B._last_ack_value == b_ack):
                    to_physical_layer(Frame(FrameKind.ACK, 0, b_ack, Packet("ACK:B")))
                    B._last_ack_value = b_ack
                    B._last_ack_epoch = epoch
                B.ack_due = False

            enable_network_layer()

        elif ev == EventType.TIMEOUT:

            key = payload
            if key >= OFFSET_B:
                B.tx_retransmit_one(key - OFFSET_B, epoch)
            else:
                A.tx_retransmit_one(key - OFFSET_A, epoch)
            enable_network_layer()

        processed += 1
        epoch += 1