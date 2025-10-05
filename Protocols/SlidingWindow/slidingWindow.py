from Utils.types import Frame, FrameKind, EventType, Packet
from Events.api import (
    wait_for_event, from_network_layer, to_physical_layer, from_physical_layer,
    to_network_layer, start_timer, stop_timer, start_ack_timer, stop_ack_timer,
    enable_network_layer, disable_network_layer
)
import random

from Utils.util import inc

OFFSET_A = 0
OFFSET_B = 100

class SW1Peer:
    """
    Inicializa A o B del protocolo SW.

    Args:
        label (str): Identificador del lado ("A" o "B").
    Returns:
        None
    """
    def __init__(self, label):
        assert label in ("A", "B")
        self.label = label # A o B
        self.seq = 0
        self.ack_expected = 0
        self.waiting = False
        self.out_buf = {} # Buffer con la data enviada
        self.frame_expected = 0
        self.ack_pending_seq = None
        self._last_sent_epoch = {}

    """
    Calcula el offset de temporizador segun en lado.
    Args:
        ninguno
    Returns:
        int: OFFSET_A si es "A" u OFFSET_B si es "B".
    """
    def tx_offset(self):
        return OFFSET_A if self.label == "A" else OFFSET_B

    """
    Funcion que calcula el ultimo numero recibido en orden contiguo (ACK acumulativo)
    Args:
        ninguno
    Returns:
        int: El numero de secuencia inmediatamente anterior a frame_expected, en modulo
    """
    def last_in_order(self):
        return inc(self.frame_expected, 1)

    """
    Funcion que decide si debe omitirse el envio de un seq en este epoch
    Args:
        seq (int): Numero de secuencia a evaluar
        epoch (int): Identificador de la iteracion actual de envio
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
        None
    """
    def _mark_sent_epoch(self, seq, epoch):
        self._last_sent_epoch[seq] = epoch

    """
    Funcion que verifica si hay espacio en la ventana de transmision
    Args:
        ninguno: Usa self.out_buf (dict/buffer de frames pendientes) y self.nr_bufs (tamano de ventana)
    Returns:
        bool: True si no hay DATA pendiente y se puede enviar.
    """
    def tx_window_has_space(self):
        return not self.waiting

    """
    Envía un nuevo DATA si hay espacio en la ventana.
    Etiqueta el paquete con el origen (A>/B>), selecciona el ACK piggyback,
    transmite y arranca el temporizador de datos.

    Args:
        epoch (int): Época actual para control de reenvíos en el mismo paso.
    Returns:
        None
    """
    def tx_push_new(self, epoch):
        sequence = self.seq
        if self._should_skip_send_this_epoch(sequence, epoch): #Si ya se envio en esta epoca, se salta
            return

        packet = from_network_layer()
        p_labeled = Packet(f"{self.label}>{packet.data}") #Etiqueta el paquete
        self.out_buf[sequence] = p_labeled #Almacena en buffer

        if self.ack_pending_seq is not None: # Si hay un ACK pendiente, se manda ese
            ack_pb = self.ack_pending_seq
        else:
            ack_pb = self.last_in_order() #Si no, el ultimo recibido en orden

        to_physical_layer(Frame(FrameKind.DATA, sequence, ack_pb, p_labeled))

        self._mark_sent_epoch(sequence, epoch)

        start_timer(self.tx_offset() + sequence)

        self.waiting = True
        self.ack_expected = sequence
        self.ack_pending_seq = None

    """
    Procesa un ACK y avanza.

    Args:
        a (int): Número de secuencia confirmado por el receptor.
    Returns:
        None
    """
    def tx_consume_ack(self, a):
        if self.waiting and a == self.ack_expected: # si esta esperando un ACK
            stop_timer(self.tx_offset() + self.ack_expected)
            self.out_buf.pop(self.ack_expected, None)
            self.waiting = False
            self.seq = inc(self.seq, 1)
            self.ack_expected = inc(self.ack_expected, 1)


    """
    Maneja la expiración del temporizador de datos y retransmite si corresponde.
    
    Args:
        timed_key (int): Clave del timer vencido.
        epoch (int): Época actual (evita reenvío duplicado en el mismo paso).
    Returns:
        None
    """
    def tx_timeout(self, timed_key, epoch):
        s = timed_key - self.tx_offset()
        if not self.waiting or s != self.ack_expected:
            return
        if self._should_skip_send_this_epoch(s, epoch):
            return

        ack_pb = self.ack_pending_seq if self.ack_pending_seq is not None else self.last_in_order()
        to_physical_layer(Frame(FrameKind.DATA, s, ack_pb, self.out_buf[s]))
        self._mark_sent_epoch(s, epoch)
        start_timer(self.tx_offset() + s)

    """
    Procesa un DATA recibido. Si es el esperado, entrega a la red y cambia el frame esperdo.

    Args:
        r_seq (int): Número de secuencia recibido.
        info (Packet): Paquete de datos contenido en el frame.
    Returns:
        None
    """
    def rx_handle_data(self, r_seq, info):
        if r_seq == self.frame_expected:
            to_network_layer(info)
            self.frame_expected = inc(self.frame_expected, 1)

        self.ack_pending_seq = self.last_in_order()

def run_sw1(steps=2000, max_seq=1):
    A = SW1Peer("A")
    B = SW1Peer("B")

    processed = 0
    epoch = 0
    ack_owner = None

    """
    Indica si alguna ventana (A o B) tiene espacio.

    Returns:
        bool: True si A o B pueden aceptar un nuevo paquete de la capa de red.
    """
    def want_app_ready():
        return A.tx_window_has_space() or B.tx_window_has_space()

    """
    Rearma el evento NETWORK_LAYER_READY.

    Returns:
        None
    """
    def rearm_ready():
        disable_network_layer()
        enable_network_layer()

    rearm_ready()
    pb_ready = 0
    ack_pure = 0

    while processed < steps:
        try:
            ev, payload = wait_for_event()
        except IndexError:
            rearm_ready()
            try:
                ev, payload = wait_for_event()
            except IndexError:
                break

        if ev == EventType.NETWORK_LAYER_READY:
            winner_is_A = (random.randint(1, 100) <= 50)
            sent = False

            if winner_is_A: #Manda A
                if A.tx_window_has_space():
                    A.tx_push_new(epoch) # A arma DATA y envía
                    sent = True
                    if ack_owner == "A": # Si A debía ACK puro, se cancela
                        stop_ack_timer()
                        ack_owner = None
                    pb_ready += 1
            else: #Manda B
                if B.tx_window_has_space():
                    B.tx_push_new(epoch)
                    sent = True
                    if ack_owner == "B":
                        stop_ack_timer()
                        ack_owner = None
                    pb_ready += 1

            if want_app_ready(): #Si aún hay espacio para otro paquete
                rearm_ready()

        elif ev == EventType.FRAME_ARRIVAL:
            recieve = from_physical_layer(payload)
            if not recieve:
                processed += 1
                epoch += 1
                continue

            if recieve.kind == FrameKind.DATA:
                data = recieve.info.data

                if data.startswith("A>"):  # DATA venía de A hacia B
                    B.rx_handle_data(recieve.seq, recieve.info) # B entrega si era lo esperado
                    B.tx_consume_ack(recieve.ack) # B consume ACK piggyback que mandó A

                    stop_ack_timer()
                    start_ack_timer()
                    ack_owner = "B"

                elif data.startswith("B>"):
                    A.rx_handle_data(recieve.seq, recieve.info)
                    A.tx_consume_ack(recieve.ack)

                    stop_ack_timer()
                    start_ack_timer()
                    ack_owner = "A"

                if want_app_ready():
                    rearm_ready()

            elif recieve.kind == FrameKind.ACK: # Llega un ACK puro
                tag = recieve.info.data
                if tag == "ACK:A":
                    B.tx_consume_ack(recieve.ack)
                elif tag == "ACK:B":
                    A.tx_consume_ack(recieve.ack)

                if want_app_ready():
                    rearm_ready()

        elif ev == EventType.ACK_TIMEOUT: # Venció el temporizador de ACK

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

            if want_app_ready():
                rearm_ready()

        elif ev == EventType.TIMEOUT:

            key = payload
            if key >= OFFSET_B:
                B.tx_timeout(key, epoch)
            else:
                A.tx_timeout(key, epoch)

            if want_app_ready():
                rearm_ready()

        processed += 1
        epoch += 1
