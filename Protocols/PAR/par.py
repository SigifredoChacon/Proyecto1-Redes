# Protocols/PAR/core.py
from Utils.types import Frame, FrameKind, EventType, Packet
from Events.api import (
    from_network_layer, to_physical_layer, from_physical_layer,
    to_network_layer, start_timer, stop_timer,
    enable_network_layer, disable_network_layer
)
from Utils.util import inc

class ParSender:
    def __init__(self):
        self.next_to_send = 0          # 0/1
        self.waiting_ack  = False      # True si hay DATA en vuelo
        self.out_buf = {0: None, 1: None}

    def on_event(self, ev, payload_or_frame):

        if ev == EventType.NETWORK_LAYER_READY:
            if not self.waiting_ack:
                p = from_network_layer()
                p = Packet(f"S>{p.data}")               # etiqueta de depuración
                seq = self.next_to_send
                self.out_buf[seq] = p
                to_physical_layer(Frame(FrameKind.DATA, seq, 0, p))
                start_timer(seq)
                self.waiting_ack = True
                disable_network_layer()
            return

        if ev == EventType.FRAME_ARRIVAL and isinstance(payload_or_frame, Frame):
            r = payload_or_frame
            if r.kind == FrameKind.ACK and self.waiting_ack and r.ack == self.next_to_send:
                try:
                    stop_timer(self.next_to_send)
                except Exception:
                    pass
                self.out_buf[self.next_to_send] = None
                self.next_to_send = inc(self.next_to_send, 1)
                self.waiting_ack = False
                enable_network_layer()
            return

        if ev == EventType.TIMEOUT:
            seq = payload_or_frame
            if self.waiting_ack and seq == self.next_to_send and self.out_buf[seq] is not None:
                to_physical_layer(Frame(FrameKind.DATA, seq, 0, self.out_buf[seq]))
                start_timer(seq)
            return


class ParReceiver:
    def __init__(self):
        self.frame_expected = 0        # 0/1

    def on_event(self, ev, payload_or_frame):
        """Solo procesa FRAME_ARRIVAL con DATA (el dispatcher filtra)."""
        if ev == EventType.FRAME_ARRIVAL and isinstance(payload_or_frame, Frame):
            r = payload_or_frame

            if r.kind == FrameKind.DATA:
                # Aceptar sólo la esperada

                if r.seq == self.frame_expected:
                    to_network_layer(r.info)
                    self.frame_expected = inc(self.frame_expected, 1)  # 0↔1
                # ACK = última buena = 1 - frame_expected
                ack_seq = (self.frame_expected + 1) % 2
                to_physical_layer(Frame(FrameKind.ACK, 0, ack_seq, Packet("ACK:R")))
