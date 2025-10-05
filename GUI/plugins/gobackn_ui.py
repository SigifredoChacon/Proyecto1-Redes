# GUI/plugins/gobackn_ui.py
from __future__ import annotations
from tkinter import ttk, messagebox
from Simulator.config import SimConfig
from GUI.protocol_base import ProtocolPlugin

# Ruta principal y fallback
from Protocols.Go_back_n.Go_back_n import run_gbn_bidirectional


"""
    Clase GUI para el protocolo Go-Back-N.
    - Bidireccional A↔B (DATA y ACK).
    - Ventana N (configurable).
    - Canal con pérdidas y corrupción.
"""
class GoBackNUI(ProtocolPlugin):
    name = "Go-Back-N"

    """
        Función interna que construye los controles específicos del protocolo.
        Args:
            self: instancia del plugin.
        Returns:
            None
    """
    def _build_controls(self):
        row = ttk.Frame(self); row.pack(fill="x", padx=6, pady=6)
        ttk.Label(row, text="Ventana N:").pack(side="left")
        self.n_spin = ttk.Spinbox(row, from_=1, to=64, width=6); self.n_spin.set("4")
        self.n_spin.pack(side="left", padx=6)

    """
        Funcion que resetea el estado del plugin y crea/bindea un Engine nuevo con la configuración dada.
        Args:
            cfg (SimConfig): configuración de la simulación.
        Returns:
            None
    """
    def reset(self, cfg):

        try:
            cfg.ready_on_enable = True
            cfg.ready_delay = 0.04
            cfg.jitter = 0.1
            cfg.data_timeout = 0.25
            cfg.ack_timeout = 0.08
        except Exception:
            setattr(cfg, "ready_on_enable", True)
            setattr(cfg, "ready_delay", 0.04)

        self.runner.build_and_bind(self.name, cfg, window_size=int(self.n_spin.get()))
        self._ran_full = False
        self._next_sender = "A"
        self._last_data_dir = "LR"
        self.anim.clear_packets()

    """
        Función que avanza la simulación k pasos.
        Args:
            k (int): número de pasos a avanzar.
        Returns:
            int: cantidad de pasos ejecutados.
    """
    def tick(self, k):
        return self.auto_step()

    """
        Función que avanza en modo automático.
        Returns:
            int: cantidad de pasos ejecutados en este ciclo.
    """
    def auto_step(self):

        if getattr(self, "_ran_full", False):
            return 0
        try:
            steps = 2000
            run_gbn_bidirectional(steps=steps, max_seq=self.runner.cfg.max_seq)
            self._ran_full = True
            return steps
        except Exception as e:
            messagebox.showerror(self.name, str(e))
            return 0

    """
        Función que decide la dirección de animación para una trama.
        Args:
            kind (str): tipo de trama ("DATA"/"ACK").
            seq (int): número de secuencia (si aplica).
            ack: número de acuse (si aplica).
            info (str, optional): información adicional de la trama. Defaults to None.
        Returns:
            str: dirección de animación ("LR" para A→B o "RL" para B→A).
    """
    @staticmethod
    def _dir_from_info(kind, info, default):
        k = (kind or "")
        s = (info or "")
        if k == "DATA":
            if s.startswith("A>"): return "LR"
            if s.startswith("B>"): return "RL"
        if k == "ACK":
            if "ACK:A" in s: return "LR"  # A→B
            if "ACK:B" in s: return "RL"  # B→A
        return default

    """
        Función que decide la dirección de animación para una trama.
        Args:
            kind (str): tipo de trama ("DATA" o "ACK").
            seq (int): número de secuencia de la trama.
            ack (int): número de acuse de la trama.
            info (str): información adicional de la trama.
        Returns:
            str: "LR" (A→B) o "RL" (B→A).
    """
    def direction_for(self, kind, seq, ack, info):
        return self._dir_from_info(kind, info, default="LR")