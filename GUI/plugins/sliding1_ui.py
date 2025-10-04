# GUI/plugins/sliding1_ui.py
from __future__ import annotations
from tkinter import ttk, messagebox
from Simulator.config import SimConfig
from GUI.protocol_base import ProtocolPlugin

# Reutilizamos la función (según tu repo)
from Protocols.SlidingWindow.slidingWindow import run_gbn_bidirectional as run_sw1



class SlidingOneBitUI(ProtocolPlugin):
    name = "Sliding Window 1-bit"

    def _build_controls(self):
        row = ttk.Frame(self); row.pack(fill="x", padx=6, pady=6)
        ttk.Label(row, text="(Full-duplex, ventana N=1)").pack(side="left")

    def reset(self, cfg: SimConfig):
        # Forzar 1-bit (N=1) + parámetros extra
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

        self.runner.build_and_bind(self.name, cfg, window_size=1)
        self._ran_full = False
        self._next_sender = "A"
        self._last_data_dir = "LR"
        self.anim.clear_packets()

    def tick(self, k: int) -> int:
        return self.auto_step()

    def auto_step(self) -> int:
        """
        Requisito: correr 2000 steps de una sola vez (no en bloques).
        """
        if getattr(self, "_ran_full", False):
            return 0
        try:
            steps = 2000
            run_sw1(steps=steps, max_seq=1)
            self._ran_full = True
            return steps
        except Exception as e:
            messagebox.showerror(self.name, str(e))
            return 0

    @staticmethod
    def _dir_from_info(kind: str, info: str | None, default: str = "LR") -> str:
        k = (kind or "").upper()
        s = (info or "").upper()
        if k == "DATA":
            if s.startswith("A>"): return "LR"
            if s.startswith("B>"): return "RL"
        if k == "ACK":
            if "ACK:A" in s: return "LR"
            if "ACK:B" in s: return "RL"
        return default

    def direction_for(self, kind: str, seq, ack, info=None) -> str:
        return self._dir_from_info(kind, info, default="LR")