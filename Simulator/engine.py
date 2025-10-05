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

        self.ready_on_enable: bool = getattr(self.cfg, "ready_on_enable", False)
        self.ready_delay: float = getattr(self.cfg, "ready_delay", 0.0)

    """
        Funcion que agenda un evento en la cola temporal del simulador
        Args:
            dt (float): Desplazamiento de tiempo (segundos) relativo al tiempo actual.
            ev (EventType): Tipo de evento a programar (NETWORK_LAYER_READY, FRAME_ARRIVAL, TIMEOUT, etc.)
            payload (Any, opcional): Datos asociados al evento (id de timer/seq para TIMEOUT)
        Returns:
            tuple: Item insertado en el heap (time, eid, ev, payload) donde 'time' es tiempo absoluto y 'eid' un id unico
    """
    def schedule(self, dt, ev, payload: Any=None):
        time = self.now + max(0.0, dt)
        item = (time, next(self.ids), ev, payload)
        heapq.heappush(self.queue, item)
        return item

    """
        Funcion que obtiene el siguiente evento valido del simulador
        Args:
            (ninguno): Usa la cola de prioridad interna y el estado de timers/ack_timer
        Returns:
            tuple[EventType, Any]: El evento aprobado y su payload asociado
        Detalles:
            - Si la cola esta vacia y la capa de red esta habilitada, agenda NETWORK_LAYER_READY inmediato.
            - Extrae el siguiente item del heap y avanza self.now.
            - Para TIMEOUT: valida que el (time,eid) coincida con el registro en self.timers[seq]; si no, descarta.
            - Para ACK_TIMEOUT: valida que coincida con self.ack_timer; si no, descarta.
            - Registra el evento en self.logs_events y lo retorna.
    """
    def wait_for_event(self):
        if not self.queue and self.net_enabled:
            self.schedule(0.0, EventType.NETWORK_LAYER_READY, None)
        while True:
            time, eid, ev, payload = heapq.heappop(self.queue)
            self.now = time

            if ev == EventType.TIMEOUT:
                seq = payload
                valid = self.timers.get(seq)
                if valid is None or valid != (time, eid):
                    continue

                self.timers.pop(seq, None)


            elif ev == EventType.ACK_TIMEOUT:
                if self.ack_timer is None or self.ack_timer != (time, eid):
                    continue
                self.ack_timer = None

            self.logs_events.append((self.now, ev.name))
            return ev, payload

    """
        Funcion que genera un paquete nuevo desde la capa de red
        Args:
            (ninguno): Usa el contador interno self.msg_i para etiquetar el mensaje
        Returns:
            Packet: Paquete con datos "MSG_{i}" e incremento de self.msg_i para la siguiente emision
    """
    def from_network_layer(self):
        p = Packet(f"MSG_{self.msg_i}")
        self.msg_i += 1
        return p

    """
        Funcion que entrega un paquete a la capa de red (registro de recepcion)
        Args:
            p (Packet): Paquete recibido desde la capa de enlace
        Returns:
            None: Agrega una entrada (tiempo actual, contenido) al log de recepciones
    """
    def to_network_layer(self, p: Packet):
        self.logs_receive.append((self.now, p.data))

    """
        Funcion que envía un frame a la capa fisica aplicando la politica del canal
        Args:
            f (Frame): Trama a transmitir (DATA o ACK)
        Returns:
            None: Registra la transmision, si el canal decide drop, no agenda nada.
                  Si decide corrupt, agenda CKSUM_ERR tras un retardo muestreado.
                  En caso normal, agenda FRAME_ARRIVAL tras el retardo del canal.
    """
    def to_physical_layer(self, f: Frame):
        self.logs_transmit.append((self.now, f))
        if self.chan.will_drop():
            return
        if self.chan.will_corrupt():
            self.schedule(self.chan.sample_delay(), EventType.CKSUM_ERR, None)
            return
        self.schedule(self.chan.sample_delay(), EventType.FRAME_ARRIVAL, f)

    """
        Funcion que obtiene el frame entregado por la capa fisica
        Args:
            payload (Any): Objeto recibido desde la cola de eventos (usualmente un Frame o None)
        Returns:
            Any: Retorna el mismo payload sin modificaciones (paso directo)
    """
    def from_physical_layer(self, payload):
        return payload

    """
        Funcion que inicia un temporizador de datos para una secuencia dada
        Args:
            seq (int): Numero de secuencia cuyo timeout se quiere programar
        Returns:
            None: Agenda un TIMEOUT tras cfg.data_timeout y registra (time,eid) en self.timers[seq]
    """
    def start_timer(self, seq: int):
        item = self.schedule(self.cfg.data_timeout, EventType.TIMEOUT, seq)
        self.timers[seq] = (item[0], item[1])

    """
        Funcion que detiene/cancela el temporizador asociado a una secuencia
        Args:
            seq (int): Numero de secuencia cuyo temporizador debe eliminarse
        Returns:
            None: Quita la entrada de self.timers si existe
    """
    def stop_timer(self, seq: int):
        self.timers.pop(seq, None)

    """
        Funcion que inicia el temporizador de ACK diferido
        Args:
            (ninguno): Usa cfg.ack_timeout para programar el evento ACK_TIMEOUT
        Returns:
            None: Agenda ACK_TIMEOUT y guarda (time,eid) en self.ack_timer
    """
    def start_ack_timer(self):
        item = self.schedule(self.cfg.ack_timeout, EventType.ACK_TIMEOUT, None)
        self.ack_timer = (item[0], item[1])

    """
        Funcion que detiene/cancela el temporizador de ACK diferido
        Args:
            (ninguno)
        Returns:
            None: Limpia el registro self.ack_timer
    """
    def stop_ack_timer(self):
        self.ack_timer = None

    """
        Funcion que habilita la capa de red (permite generar eventos de READY)
        Args:
            (ninguno): Lee flags ready_on_enable y ready_delay para agendar NETWORK_LAYER_READY
        Returns:
            None: Activa net_enabled y, si corresponde, agenda NETWORK_LAYER_READY tras ready_delay
    """
    def enable_network_layer(self):
        self.net_enabled = True
        if self.ready_on_enable:
            self.schedule(self.ready_delay, EventType.NETWORK_LAYER_READY, None)

    """
        Funcion que deshabilita la capa de red (no se generaran eventos de READY)
        Args:
            (ninguno)
        Returns:
            None: Desactiva net_enabled
    """
    def disable_network_layer(self):
        self.net_enabled = False

    """
        Funcion que toma una captura del estado y los registros de la simulacion
        Args:
            (ninguno)
        Returns:
            dict: Estructura con:
                - "time" (float): Tiempo simulado actual (self.now)
                - "events" (list[tuple]): Historial de eventos (tiempo, nombre_evento)
                - "tx" (list[tuple]): Log de transmisiones como (t, kind, seq, ack, info)
                - "rx" (list[tuple]): Log de recepciones como (t, data)
    """
    def snapshot(self):
        return {
            "time": self.now,
            "events": list(self.logs_events),
            "tx": [(t, f.kind.name, f.seq, f.ack, f.info.data) for t, f in self.logs_transmit],
            "rx": list(self.logs_receive),
        }