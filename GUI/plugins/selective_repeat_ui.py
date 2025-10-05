# GUI/plugins/selective_repeat_ui.py
from __future__ import annotations
from tkinter import ttk, messagebox
from Simulator.config import SimConfig
from GUI.protocol_base import ProtocolPlugin


from Protocols.SelectiveRepeat.selectiveRepeat import run_sr_bidirectional



class SelectiveRepeatUI(ProtocolPlugin):
    name = "Selective Repeat"

    """
        Funcion que construye los controles de configuracion del protocolo en la UI
        Args:
            (ninguno): Usa el propio contenedor self para crear widgets de Tkinter/ttk
        Returns:
            None: Inserta un Spinbox para el tamano de ventana (N) dentro del layout
    """
    def _build_controls(self):
        row = ttk.Frame(self)
        row.pack(fill="x", padx=6, pady=6)
        ttk.Label(row, text="Ventana N:").pack(side="left")
        self.n_spin = ttk.Spinbox(row, from_=1, to=64, width=6)
        self.n_spin.set("4")
        self.n_spin.pack(side="left", padx=6)



    """
        Funcion que reinicia/arma el runner del protocolo con la configuracion adecuada
        Args:
            cfg (SimConfig): Configuracion base de la simulacion (se ajustan ready_on_enable, ready_delay, etc.)
        Returns:
            None: Actualiza cfg con defaults, construye y asocia el runner, resetea flags internos y limpia la animacion
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
        Funcion que ejecuta un tick de simulacion para K pasos
        Args:
            k (int): Cantidad de pasos solicitados por el usuario
        Returns:
            int: Pasos realmente ejecutados (delegado a auto_step)
    """
    def tick(self, k: int) -> int:
        return self.auto_step()


    """
        Funcion que corre automaticamente la simulacion completa de SR (minimo 2000 steps)
        Args:
            (ninguno): Usa self.runner.cfg para leer max_seq y dispara run_sr_bidirectional
        Returns:
            int: Numero de pasos procesados (2000 si corre exitosamente, 0 si hubo error)
    """

    def auto_step(self):

        if getattr(self, "_ran_full", False):
            return 0
        try:
            steps = 2000
            run_sr_bidirectional(steps=steps, max_seq=self.runner.cfg.max_seq)
            self._ran_full = True
            return steps
        except Exception as e:
            messagebox.showerror(self.name, str(e))
            return 0


    """
        Funcion que deduce la direccion de animacion segun el tipo de frame e informacion
        Args:
            kind (str): Tipo de frame ("DATA" o "ACK")
            info (str|None): Campo de informacion; para DATA inicia con "A>" o "B>", para ACK contiene "ACK:A" o "ACK:B"
            default (str): Direccion por defecto ("LR" izquierda->derecha, "RL" derecha->izquierda)
        Returns:
            str: "LR" si el flujo es A->B, "RL" si es B->A, o default si no se puede inferir
    """

    @staticmethod
    def _dir_from_info(kind, info, default= "LR"):
        k = (kind or "")
        s = (info or "")
        if k == "DATA":
            if s.startswith("A>"): return "LR"
            if s.startswith("B>"): return "RL"
        if k == "ACK":
            if "ACK:A" in s: return "LR"
            if "ACK:B" in s: return "RL"
        return default

    """
        Funcion que retorna la direccion de dibujo/animacion para un frame
        Args:
            kind (str): Tipo de frame ("DATA" o "ACK")
            seq (int): Numero de secuencia (no usado para direccion, puede ser util para overlays)
            ack (int): Numero ACK acumulativo (no usado para direccion)
            info (str|None): Texto/etiqueta para inferir origen/destino
        Returns:
            str: "LR" o "RL" segun el origen/destino inferido por _dir_from_info
    """
    def direction_for(self, kind, seq, ack, info=None):
        return self._dir_from_info(kind, info, default="LR")