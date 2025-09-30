from Utils.types import Frame, FrameKind, EventType
from Events.api import (
    wait_for_event, from_network_layer, to_physical_layer,
    from_physical_layer, to_network_layer
)

def sender_utopia(steps=10):
    processed = 0
    while processed < steps:
        ev, _ = wait_for_event()
        if ev == EventType.NETWORK_LAYER_READY:
            p = from_network_layer()
            f = Frame(FrameKind.DATA, seq=0, ack=0, info=p)
            to_physical_layer(f)

            processed += 1

def receive_utopia(steps=10):
    processed = 0
    while processed < steps:
        ev, payload = wait_for_event()
        if ev == EventType.FRAME_ARRIVAL:
            r = from_physical_layer(payload)
            if r and r.kind == FrameKind.DATA:
                to_network_layer(r.info)
            processed += 1