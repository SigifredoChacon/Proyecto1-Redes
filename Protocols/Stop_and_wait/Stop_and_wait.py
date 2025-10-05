from __future__ import annotations
from Utils.types import Frame, FrameKind, EventType, Packet
from Events.api import (
    wait_for_event, from_network_layer, to_physical_layer, from_physical_layer,
    to_network_layer, enable_network_layer, disable_network_layer,
    start_timer, stop_timer,
)

num_sequence = 0
buffer_pkt: Packet | None = None
waiting_ack = False

"""
    Funcion que construye un frame de datos
    Args:
        seq_num (int): Numero de secuencia del frame
        pkt (Packet): Paquete de datos a enviar
    Returns:
        Frame: Frame de datos construido
"""
def build_data_frame(seq_num, pkt):
    return Frame(FrameKind.DATA, seq_num, 0, Packet(f"A>{pkt.data}"))

"""
    Funcion que construye un frame de ACK
    Args:
        ack_num (int): Numero de ACK del frame
    Returns:
        Frame: Frame de ACK construido
"""
def build_ack_frame(ack_num):
    return Frame(FrameKind.ACK, 0, ack_num, Packet("ACK:B"))

"""
    Funcion que implementa el emisor del protocolo Stop-and-Wait
    Args:
        steps (int): Numero de pasos a ejecutar 
    Returns:
        None
"""
def sender_sw(steps):

    global num_sequence, buffer_pkt, waiting_ack

    if not waiting_ack:
        enable_network_layer()
    else:
        disable_network_layer()

    processed = 0
    while processed < steps:
        event, payload = wait_for_event()

        if event == EventType.NETWORK_LAYER_READY and not waiting_ack:

            buffer_pkt = from_network_layer()
            frame = build_data_frame(num_sequence, buffer_pkt)
            to_physical_layer(frame)

            start_timer(num_sequence)
            waiting_ack = True
            disable_network_layer()
            processed += 1
            continue

        if event == EventType.FRAME_ARRIVAL and waiting_ack:

            received_frame = from_physical_layer(payload)
            if received_frame and received_frame.kind == FrameKind.ACK:

                if int(received_frame.ack) == num_sequence:
                    stop_timer(num_sequence)
                    num_sequence ^= 1
                    buffer_pkt = None
                    waiting_ack = False
                    enable_network_layer()
            processed += 1
            continue

        if event == EventType.TIMEOUT and waiting_ack:

            if buffer_pkt is not None:
                frame = build_data_frame(num_sequence, buffer_pkt)
                to_physical_layer(frame)
                start_timer(num_sequence)
            processed += 1
            continue


        processed += 1


#  Receptor B
expected = 0

"""
    Funcion que implementa el receptor del protocolo Stop-and-Wait
    Args:
        steps (int): Numero de pasos a ejecutar
    Returns:
        None
"""
def receiver_sw(steps):

    global expected

    processed = 0
    while processed < steps:
        event, payload = wait_for_event()

        if event == EventType.FRAME_ARRIVAL:
            received_frame = from_physical_layer(payload)
            if received_frame and received_frame.kind == FrameKind.DATA:
                if int(received_frame.seq) == expected:
                    to_network_layer(received_frame.info)
                    ack_bit = expected
                    expected ^= 1
                else:
                    ack_bit = 1 - expected

                to_physical_layer(build_ack_frame(ack_bit))

        processed += 1