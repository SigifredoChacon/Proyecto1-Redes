import heapq, itertools
from typing import Any, Dict, Tuple, Optional
from Utils.types import EventType, Packet, Frame, FrameKind
from Simulator.config import SimConfig
from Simulator.channel import ChannelPolicy

class Engine:
    def __init__(self, cfg: Optional[SimConfig] = None):
        self.cfg = cfg or SimConfig()
        self.chan = ChannelPolicy(self.cfg)
        self.now: float = 0.0
        self.queue = []
        self.ids = itertools.count()
        self.net_enabled = True
        self.msg_i = 0

        self.timers: Dict[int, Tuple[float,int]] = {}
        self.ack_timer: Optional[Tuple[float,int]] = None

        self.logs_transmit = []
        self.logs_receive = []
        self.logs_events = []
        # === NUEVO: política de READY al habilitar la red (ACK-wake) ===
        # Si tu SimConfig ya trae estos campos, se usan; si no, se aplican por defecto.
        self.ready_on_enable: bool = getattr(self.cfg, "ready_on_enable", False)
        self.ready_delay: float = getattr(self.cfg, "ready_delay", 0.0)

    def schedule(self, dt: float, ev: EventType, payload: Any=None):
        time = self.now + max(0.0, dt)
        item = (time, next(self.ids), ev, payload)
        heapq.heappush(self.queue, item)
        return item

    def wait_for_event(self):
        # Si cola vacía y red habilitada, inyecta un READY inmediato
        if not self.queue and self.net_enabled:
            self.schedule(0.0, EventType.NETWORK_LAYER_READY, None)

        # CHANGED: bucle para descartar eventos "stale" (timers fantasma)
        while True:
            time, eid, ev, payload = heapq.heappop(self.queue)  # CHANGED (capturo eid)
            self.now = time

            # Filtrado de TIMEOUT de DATA: validar contra self.timers[seq]
            if ev == EventType.TIMEOUT:
                seq = payload
                valid = self.timers.get(seq)
                if valid is None or valid != (time, eid):
                    # Es un timeout viejo (timer cancelado/reprogramado) -> descartar
                    continue
                # Es válido: consume el registro para que no se reprograme solo
                self.timers.pop(seq, None)

            # Filtrado de ACK_TIMEOUT: validar contra self.ack_timer
            elif ev == EventType.ACK_TIMEOUT:
                if self.ack_timer is None or self.ack_timer != (time, eid):
                    # ACK timeout viejo -> descartar
                    continue
                # Es válido: limpia para evitar repetición
                self.ack_timer = None

            # Registrar el evento aceptado y devolverlo
            self.logs_events.append((self.now, ev.name))
            return ev, payload

    def from_network_layer(self):
        p = Packet(f"MSG_{self.msg_i}")
        self.msg_i += 1
        return p

    def to_network_layer(self, p: Packet):
        self.logs_receive.append((self.now, p.data))

    def to_physical_layer(self, f: Frame):
        self.logs_transmit.append((self.now, f))
        if self.chan.will_drop():
            return
        if self.chan.will_corrupt():
            self.schedule(self.chan.sample_delay(), EventType.CKSUM_ERR, None)
            return
        self.schedule(self.chan.sample_delay(), EventType.FRAME_ARRIVAL, f)

    def from_physical_layer(self, payload):
        return payload


    def start_timer(self, seq: int):
        item = self.schedule(self.cfg.data_timeout, EventType.TIMEOUT, seq)
        self.timers[seq] = (item[0], item[1])

    def stop_timer(self, seq: int):
        self.timers.pop(seq, None)

    def start_ack_timer(self):
        item = self.schedule(self.cfg.ack_timeout, EventType.ACK_TIMEOUT, None)
        self.ack_timer = (item[0], item[1])

    def stop_ack_timer(self):
        self.ack_timer = None

    def enable_network_layer(self):
        self.net_enabled = True
        # === NUEVO: al habilitar red, programa un READY pronto (ACK-wake) ===
        if self.ready_on_enable:
            self.schedule(self.ready_delay, EventType.NETWORK_LAYER_READY, None)

    def disable_network_layer(self):
        self.net_enabled = False


    def snapshot(self):
        return {
            "time": self.now,
            "events": list(self.logs_events),
            "tx": [(t, f.kind.name, f.seq, f.ack, f.info.data) for t, f in self.logs_transmit],
            "rx": list(self.logs_receive),
        }