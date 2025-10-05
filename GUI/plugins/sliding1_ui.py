from __future__ import annotations
from tkinter import ttk, messagebox
from Simulator.config import SimConfig
from GUI.protocol_base import ProtocolPlugin
from Protocols.SlidingWindow.slidingWindow import run_sw1

class SlidingOneBitUI(ProtocolPlugin):
    name = "Sliding Window 1-bit"

    """
    Construye los controles del panel de la GUI para SW1.

    Args:
        (none)

    Returns:
        None
    """
    def _build_controls(self):
        row = ttk.Frame(self)
        row.pack(fill="x", padx=6, pady=6)
        ttk.Label(row, text="(Full-duplex, ventana N=1)").pack(side="left")

    """
    Reinicia y arma el entorno de simulación forzando N=1 y parámetros útiles.
    Limpia el lienzo/estado de ejecución.

    Args:
        cfg (SimConfig): Configuración del simulador (delays, timeouts, etc.).

    Returns:
        None
    """
    def reset(self, cfg):
        cfg.max_seq = 1
        cfg.nr_bufs = 1
        cfg.jitter = 0.1
        cfg.data_timeout = 0.25
        cfg.ack_timeout = 0.08
        try:
            cfg.ready_on_enable = True
            cfg.ready_delay = 0.04
        except Exception:
            setattr(cfg, "ready_on_enable", True)
            setattr(cfg, "ready_delay", 0.04)

        self.runner.build_and_bind(self.name, cfg, window_size=1) #Conecta la UI con el Engine
        self._ran_full = False # Dispoible para ejecutar
        self._next_sender = "A"
        self._last_data_dir = "LR"
        self.anim.clear_packets() #Limpia el canvas

    """
    Avanza la simulación, delega en auto_step().

    Args:
        k (int): Cantidad solicitada de pasos (no se usa aquí).

    Returns:
        int: Número de pasos efectivamente ejecutados (0 o 2000).
    """
    def tick(self, k):

        return self.auto_step()

    """
    Ejecuta la simulación en un solo bloque grande.

    Args:
       (none)

    Returns:
       int: 2000 en la primera llamada exitosa 0 en llamadas posteriores.
    """
    def auto_step(self):
        if self._ran_full:
            return 0
        try:
            steps = 2000
            run_sw1(steps=steps, max_seq=1)
            self._ran_full = True
            return steps
        except Exception as e:
            messagebox.showerror(self.name, str(e))
            return 0

    """
    Decide la dirección de animación a partir del contenido del frame.
    Para DATA se basa en los prefijos "A>" / "B>", para ACK se basa en las etiquetas "ACK:A" / "ACK:B".

    Args:
        kind (str): Tipo de trama ("DATA" o "ACK").
        info (str): Texto auxiliar del frame ( "A>...", "ACK:B").
        default (str): Dirección por defecto si no se reconoce ("LR").

    Returns:
        str: "LR" para A→B, "RL" para B→A.
    """
    @staticmethod
    def _dir_from_info(kind, info, default: str = "LR"):
        if kind == "DATA":
            if info.startswith("A>"):
                return "LR"
            if info.startswith("B>"):
                return "RL"
        if kind == "ACK":
            if "ACK:A" in info:
                return "LR"
            if "ACK:B" in info:
                return "RL"
        return default

    """
    Decide la dirección de dibujo en el canvas para cada frame.

    Args:
        kind (str): Tipo de trama ("DATA" o "ACK").
        seq (Any): Número de secuencia (no se usa).
        ack (Any): Número de ack (no se usa).
        info (Any): Información opcional asociada al frame.

    Returns:
        str: "LR" o "RL" según lo que detecte _dir_from_info().
    """
    def direction_for(self, kind: str, seq, ack, info=None) :
        return self._dir_from_info(kind, info, default="LR")