from Utils.types import Frame, FrameKind, EventType
from Events.api import (
    wait_for_event, from_network_layer, to_physical_layer,
    from_physical_layer, to_network_layer
)
"""
    Funcion que envia paquetes sin ACKs ni temporizadores
    Args:
        steps (int): Numero maximo de eventos a procesar, cada NETWORK_LAYER_READY cuenta un envio
    Returns:
        None: Toma un paquete de la capa de red y lo manda como DATA (seq=0, ack=0) sin control de errores
"""
def sender_utopia(steps=10):
    processed = 0
    while processed < steps:
        ev, _ = wait_for_event()
        if ev == EventType.NETWORK_LAYER_READY:
            p = from_network_layer()
            f = Frame(FrameKind.DATA, seq=0, ack=0, info=p)
            to_physical_layer(f)

            processed += 1


"""
    Funcion que recibe y entrega datos sin validaciones
    Args:
        steps (int): Numero maximo de eventos a procesar, cada FRAME_ARRIVAL intenta entregar a la red
    Returns:
        None: Si llega un DATA valido, entrega r.info a la capa de red sin checks adicionales
"""

def receive_utopia(steps=10):
    processed = 0
    while processed < steps:
        ev, payload = wait_for_event()
        if ev == EventType.FRAME_ARRIVAL:
            r = from_physical_layer(payload)
            if r and r.kind == FrameKind.DATA:
                to_network_layer(r.info)
            processed += 1