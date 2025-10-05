# Protocols/PAR/core.py
from Utils.types import Frame, FrameKind, EventType, Packet
from Events.api import (
    from_network_layer, to_physical_layer, from_physical_layer,
    to_network_layer, start_timer, stop_timer,
    enable_network_layer, disable_network_layer)
from Utils.util import inc

#Clase emisor del protocolo PAR.
class ParSender:

    """
    Inicializa el emisor PAR.
    Args:
        next_to_send (int): Siguiente número de secuencia a enviar (0 o 1).
        waiting_ack (bool): Indica si hay una trama DATA en vuelo esperando ACK.
        out_buf (dict[int, Packet|None]): Buffer de reenvío por bit (0/1).
    Returns:
        None
    """
    def __init__(self):
        self.next_to_send = 0
        self.waiting_ack  = False # Hay data en camino
        self.out_buf = {0: None, 1: None} # Copia del packet que se envió

    """
    Se encarga de crear y enviar los frames, ademas de verificar el timeout y el ACK.
    Args:
        ev (EventType): Tipo de evento (NETWORK_LAYER_READY, FRAME_ARRIVAL, TIMEOUT).
        payload_or_frame: Entero 'seq' para TIMEOUT, o Frame recibido para FRAME_ARRIVAL (ACK).
    returns:
        None
    """
    def on_event(self, ev, payload_or_frame):
        if ev == EventType.NETWORK_LAYER_READY: # Si la capa de red esta lista para mandar un mensaje
            if not self.waiting_ack:            # Si no está esperando un ACK
                packet = from_network_layer()
                packet = Packet(f"A>{packet.data}")       #Etiqueta el mensaje
                seq = self.next_to_send
                self.out_buf[seq] = packet
                to_physical_layer(Frame(FrameKind.DATA, seq, 0, packet)) # Envia el mensaje
                start_timer(seq)
                self.waiting_ack = True
                disable_network_layer()
            return

        if ev == EventType.FRAME_ARRIVAL and isinstance(payload_or_frame, Frame): #Si el evento es la llegada de un frame (ACK)
            receive = payload_or_frame
            if receive.kind == FrameKind.ACK and self.waiting_ack and receive.ack == self.next_to_send: # Es el ACK correcto
                stop_timer(self.next_to_send)
                self.out_buf[self.next_to_send] = None #Limpia el buffer
                self.next_to_send = inc(self.next_to_send, 1)
                self.waiting_ack = False #Apaga la bandera de esperar ACK
                enable_network_layer()
            return

        if ev == EventType.TIMEOUT: #Si el timer vence
            seq = payload_or_frame
            if self.waiting_ack and seq == self.next_to_send and self.out_buf[seq] is not None: #Si se espera un ACK, y el numero de secuencia no ha cambiado y el buffer no esta vacio
                to_physical_layer(Frame(FrameKind.DATA, seq, 0, self.out_buf[seq]))
                start_timer(seq)
            return

"""
    Clase receptor del protocolo PAR.
"""
class ParReceiver:
    """
    Inicializa el receptor PAR.
    Atributos:
        frame_expected (int): Número de secuencia que se espera recibir (0 o 1).
    Returns:
        None
    """
    def __init__(self):
        self.frame_expected = 0        # 0/1

    """
    Se encarga de recibir el frame y enviar un ACK de confimacion.
    Args:
        ev (EventType): Tipo de evento; en este caso solamente FRAME_ARRIVAL.
        payload_or_frame (): Frame recibido desde la capa física.
    Returns:
        None
    """
    def on_event(self, ev, payload_or_frame):
        if ev == EventType.FRAME_ARRIVAL and isinstance(payload_or_frame, Frame):
            receive = payload_or_frame

            if receive.kind == FrameKind.DATA:
                if receive.seq == self.frame_expected: #Si es el frame esperado
                    to_network_layer(receive.info)
                    self.frame_expected = inc(self.frame_expected, 1)  #0/1

                ack_seq = (self.frame_expected + 1) % 2
                to_physical_layer(Frame(FrameKind.ACK, 0, ack_seq, Packet("ACK:R"))) #Envia el ACK
