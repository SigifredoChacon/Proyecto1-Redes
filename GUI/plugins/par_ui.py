# GUI/plugins/par_ui.py
from __future__ import annotations
from tkinter import ttk, messagebox
from Simulator.config import SimConfig
from GUI.protocol_base import ProtocolPlugin
from Utils.types import EventType, FrameKind

# Dependencias del protocolo PAR (rutas contempladas)
try:
    from Events.api import wait_for_event, from_physical_layer
    from Events.api import enable_network_layer, disable_network_layer
except Exception:
    from Events.api import wait_for_event, from_physical_layer
    from Events.api import enable_network_layer, disable_network_layer

from Protocols.PAR.par import ParSender, ParReceiver



class PARUI(ProtocolPlugin):
    name = "PAR"

    def _build_controls(self):
        row = ttk.Frame(self); row.pack(fill="x", padx=6, pady=6)
        ttk.Label(row, text="(Unidireccional A→B, ventana=1)").pack(side="left")

    def reset(self, cfg: SimConfig):
        # PAR: espacio/ventana de 1 bit
        cfg.max_seq = 1
        cfg.nr_bufs = 1
        self.runner.build_and_bind(self.name, cfg, window_size=1)
        # Instancias del emisor y receptor como en run_par.py
        self.S = ParSender()
        self.R = ParReceiver()
        self.anim.clear_packets()

    # Compatibilidad con base (algunos proyectos piden tick)
    def tick(self, k: int) -> int:
        total = 0
        for _ in range(max(1, int(k))):
            total += self.auto_step()
        return total

    def auto_step(self) -> int:
        """
        Procesa varios eventos del Engine (similar a run_par.py).
        Retorna cuántos sub-pasos avanzó, tolerando cola vacía.
        """
        N = 200  # tamaño de bloque razonable
        processed = 0

        # Si el emisor no está esperando, la network layer estará habilitada;
        # en caso contrario, es normal que la cola quede vacía por momentos.
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

    def direction_for(self, kind: str, seq, ack, info=None) -> str:
        # En PAR, DATA va LR (A→B) y ACK puro regresa RL (B→A)
        return "LR" if str(kind).upper() == "DATA" else "RL"