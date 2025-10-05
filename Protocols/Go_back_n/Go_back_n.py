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


"""
    Clase GBNPeer: maneja el estado y la lógica de un peer GBN (A o B).
"""
class GBNPeer:

    def __init__(self, label, max_seq):
        assert label in ("A", "B")
        self.label = label
        self.max_seq = max_seq
        self.window = max_seq


        self.ack_expected = 0
        self.next_to_send = 0
        self.nbuffered = 0
        self.out_buf = {}


        self.frame_expected = 0


        self.last_sent_epoch = {}

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
        Funcion que verifica si hay espacio en la ventana de transmision
        Args:
            (ninguno): Usa self.out_buf (dict/buffer de frames pendientes) y self.nr_bufs (tamano de ventana)
        Returns:
            bool: True si el emisor puede enviar otro frame (len(out_buf) < nr_bufs), False en caso contrario
    """
    def tx_window_has_space(self):
        return self.nbuffered < self.window

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
    def should_skip_send_this_epoch(self, seq, epoch):
        return self.last_sent_epoch.get(seq) == epoch

    """
        Funcion que marca que un numero de secuencia fue enviado en un epoch especifico
        Args:
            seq (int): Numero de secuencia enviado
            epoch (int): Identificador del epoch en el que se envio
        Returns:
            None: Actualiza el registro interno self._last_sent_epoch con la pareja (seq, epoch)
    """
    def mark_sent_epoch(self, seq, epoch):
        self.last_sent_epoch[seq] = epoch

    """
        Función que maneja la llegada de un nuevo paquete desde la capa de red.
        Arg:
            epoch (int): Identificador de la iteracion/epoch actual de envio
        Returns:
            None
    """
    def tx_push_new(self, epoch):

        p = from_network_layer()
        p_labeled = Packet(f"{self.label}>{p.data}")
        s = self.next_to_send

        self.out_buf[s] = p_labeled
        self.nbuffered += 1
        self.send_data(s, epoch)
        self.next_to_send = inc(s, self.max_seq)

    """
        Función que envía un frame DATA si no se ha enviado ya en este epoch.
        Args:
            seq (int): Número de secuencia del frame a enviar
            epoch (int): Identificador de la iteración/epoch actual de envío
        Returns:
            None
    """
    def send_data(self, seq, epoch):

        if self.should_skip_send_this_epoch(seq, epoch):
            return
        ack_pb = self.last_in_order()
        to_physical_layer(Frame(FrameKind.DATA, seq, ack_pb, self.out_buf[seq]))
        self.mark_sent_epoch(seq, epoch)

        if seq == self.ack_expected:
            start_timer(self.tx_offset() + seq)

    """
         Función que maneja la llegada de un ACK acumulativo.
         Args:
             ack (int): Número de secuencia del ACK recibido
         Returns:
             None
    """
    def tx_consume_ack(self, ack):

        advanced = False
        while (self.nbuffered > 0) and between(self.ack_expected, ack, self.next_to_send):
            old_base = self.ack_expected

            try:
                stop_timer(self.tx_offset() + old_base)
            except Exception:
                pass

            self.out_buf.pop(old_base, None)
            self.nbuffered -= 1
            self.ack_expected = inc(self.ack_expected, self.max_seq)
            advanced = True

        if advanced and self.nbuffered > 0:
            try:
                start_timer(self.tx_offset() + self.ack_expected)
            except Exception:
                pass

    """
        Función que maneja el timeout del temporizador.
        Args:
            epoch (int): Identificador de la iteración/epoch actual de envío
        Returns:
            None
    """
    def tx_timeout(self, epoch):

        if self.nbuffered == 0:
            return
        s = self.ack_expected
        for _ in range(self.nbuffered):
            self.send_data(s, epoch)
            s = inc(s, self.max_seq)


    """
       Función que maneja la llegada de un frame DATA.
       Args:
           r_seq (int): Número de secuencia del frame recibido
           info (Packet): Contenido del frame recibido
       Returns:
           None
    """
    def rx_handle_data(self, r_seq: int, info):

        if r_seq == self.frame_expected:
            to_network_layer(info)
            self.frame_expected = inc(self.frame_expected, self.max_seq)


"""
    Función principal que ejecuta el protocolo GBN bidireccional.
    Args:
        steps (int): Número de pasos a ejecutar en la simulación
        max_seq (int): Tamaño máximo del número de secuencia (N)
        burst_k (int | None): Tamaño de ráfaga para envíos 
        rng_seed (int | None): Semilla para el generador de números aleatorios
    Returns:
        None
"""
def run_gbn_bidirectional(steps, max_seq, burst_k=None, rng_seed=None):

    if rng_seed is not None:
        random.seed(rng_seed)

    A = GBNPeer("A", max_seq=max_seq)
    B = GBNPeer("B", max_seq=max_seq)


    if burst_k is None:
        burst_k = A.window

    enable_network_layer()

    processed = 0
    epoch = 0
    ack_owner = None

    """
        Función que maneja el envío en ráfaga desde un peer.
        Args:
            peer (GBNPeer): El peer (A o B) desde el cual se envían los frames
            epoch_val (int): Identificador de la iteración/epoch actual de envío
        Returns:
            int: Número de frames enviados en esta ráfaga
    """
    def burst_send(peer, epoch_val):

        nonlocal ack_owner

        free = peer.window - peer.nbuffered
        if free <= 0:
            return 0
        budget = min(burst_k, free)
        sent = 0
        for _ in range(budget):
            peer.tx_push_new(epoch_val)
            sent += 1

            if (peer.label == "A" and ack_owner == "A") or (peer.label == "B" and ack_owner == "B"):
                try:
                    stop_ack_timer()
                except Exception:
                    pass
                ack_owner = None
        return sent

    while processed < steps:
        event, payload = wait_for_event()

        if event == EventType.NETWORK_LAYER_READY:
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

        elif event == EventType.FRAME_ARRIVAL:
            r = from_physical_layer(payload)
            if not r:
                processed += 1
                epoch += 1
                continue

            if r.kind == FrameKind.DATA:
                data = r.info.data

                if data.startswith("A>"):

                    B.rx_handle_data(r.seq, r.info)
                    B.tx_consume_ack(r.ack)

                    try:
                        stop_ack_timer()
                    except Exception:
                        pass
                    start_ack_timer()
                    ack_owner = "B"

                elif data.startswith("B>"):

                    A.rx_handle_data(r.seq, r.info)
                    A.tx_consume_ack(r.ack)

                    try:
                        stop_ack_timer()
                    except Exception:
                        pass
                    start_ack_timer()
                    ack_owner = "A"

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

        elif event == EventType.ACK_TIMEOUT:

            if ack_owner == "A":
                to_physical_layer(Frame(FrameKind.ACK, 0, A.last_in_order(), Packet("ACK:A")))
                ack_owner = None
            elif ack_owner == "B":
                to_physical_layer(Frame(FrameKind.ACK, 0, B.last_in_order(), Packet("ACK:B")))
                ack_owner = None
            enable_network_layer()

        elif event == EventType.TIMEOUT:

            key = payload
            if key >= OFFSET_B:
                B.tx_timeout(epoch)
                if ack_owner == "B":
                    try:
                        stop_ack_timer()
                    except Exception:
                        pass
                    ack_owner = None
            else:
                A.tx_timeout(epoch)
                if ack_owner == "A":
                    try:
                        stop_ack_timer()
                    except Exception:
                        pass
                    ack_owner = None
            enable_network_layer()

        processed += 1
        epoch += 1