# Protocols/StopAndWait/stop_and_wait.py
from Utils.types import Frame, FrameKind, EventType, Packet
from Events.api import (
    wait_for_event, from_network_layer, to_physical_layer, from_physical_layer,
    to_network_layer, enable_network_layer, disable_network_layer
)

def sender_sw(steps=10):

    waiting_dummy = False


    enable_network_layer()

    processed = 0
    while processed < steps:
        ev, payload = wait_for_event()

        if ev == EventType.NETWORK_LAYER_READY and not waiting_dummy:

            p = from_network_layer()
            p_labeled = Packet(f"S>{p.data}")


            to_physical_layer(Frame(FrameKind.DATA, 0, 0, p_labeled))


            waiting_dummy = True
            disable_network_layer()

            processed += 1
            continue

        if ev == EventType.FRAME_ARRIVAL and waiting_dummy:

            r = from_physical_layer(payload)

            if r:
                waiting_dummy = False
                enable_network_layer()

            processed += 1
            continue




def receiver_sw(steps=10):

    processed = 0
    while processed < steps:
        ev, payload = wait_for_event()

        if ev == EventType.FRAME_ARRIVAL:
            r = from_physical_layer(payload)
            if r and r.kind == FrameKind.DATA:

                to_network_layer(r.info)


                to_physical_layer(Frame(FrameKind.ACK, 0, 0, Packet("DUMMY")))

            processed += 1
            continue


