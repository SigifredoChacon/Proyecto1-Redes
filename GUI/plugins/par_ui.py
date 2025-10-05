from __future__ import annotations
from tkinter import ttk, messagebox
from Simulator.config import SimConfig
from GUI.protocol_base import ProtocolPlugin
from Utils.types import EventType, FrameKind
from Events.api import wait_for_event, from_physical_layer
from Events.api import enable_network_layer, disable_network_layer
from Protocols.PAR.par import ParSender, ParReceiver


class PARUI(ProtocolPlugin):
    name = "PAR"

    """
    Construye los controles del panel de PAR en la GUI.

    Args:
        (none)

    Returns:
        None
    """
    def _build_controls(self):
        row = ttk.Frame(self)
        row.pack(fill="x", padx=6, pady=6)
        ttk.Label(row, text="(Unidireccional A→B, ventana=1)").pack(side="left")

    """
    Reinicia lasimulación para PAR y crea emisor/receptor.

    Args:
        cfg (SimConfig): Configuración base del simulador.

    Returns:
        None
    """
    def reset(self, cfg):
        cfg.max_seq = 1
        cfg.nr_bufs = 1
        cfg.jitter = 0.1
        cfg.data_timeout = 0.25
        cfg.ack_timeout = 0.08
        self.runner.build_and_bind(self.name, cfg, window_size=1)
        self.S = ParSender()
        self.R = ParReceiver()
        self.anim.clear_packets()

    """
    Avanza la simulación en k pasos, acumulando los eventos procesados.

    Args:
        k (int): Cantidad de pasos a ejecutar.

    Returns:
        int: Total de eventos ejecutados.
    """
    def tick(self, k: int) -> int:
        total = 0
        for _ in range(max(1, int(k))):
            total += self.auto_step()
        return total

    """
    Ejecuta una ráfaga de eventos.
    Entrega DATA al receptor y ACK al emisor, maneja NETWORK_LAYER_READY/TIMEOUT en el emisor.

    Args:
        (none)

    Returns:
        int: Número de eventos procesados.
    """
    def auto_step(self) -> int:
        N = 200
        processed = 0

        try:
            while processed < N:
                try:
                    ev, payload = wait_for_event()
                except IndexError:
                    # cola vacía: no hay eventos listos ahora mismo
                    break

                if ev == EventType.FRAME_ARRIVAL:
                    f = from_physical_layer(payload)
                    if f:
                        if f.kind == FrameKind.DATA:
                            self.R.on_event(ev, f)   # receptor procesa DATA
                        elif f.kind == FrameKind.ACK:
                            self.S.on_event(ev, f)   # emisor procesa ACK

                elif ev in (EventType.NETWORK_LAYER_READY, EventType.TIMEOUT):
                    self.S.on_event(ev, payload)

                processed += 1

            return processed

        except Exception as e:
            messagebox.showerror(self.name, str(e))
            return processed

    """
    Decide la dirección de animación para el canvas.

    Args:
        kind (str): Tipo de trama ("DATA" o "ACK").
        seq (Any): Número de secuencia (no usado aquí).
        ack (Any): Número de ack (no usado aquí).
        info (Any): Información opcional del frame (no usado aquí).

    Returns:
        str: "LR" para DATA (A→B) o "RL" para ACK (B→A).
    """
    def direction_for(self, kind, seq, ack, info=None):
        return "LR" if str(kind) == "DATA" else "RL"