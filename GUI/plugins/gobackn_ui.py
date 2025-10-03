# GUI/plugins/gobackn_ui.py
from __future__ import annotations
from tkinter import ttk, messagebox
from Simulator.config import SimConfig
from GUI.protocol_base import ProtocolPlugin

# Ruta principal y fallback
from Protocols.Go_back_n.Go_back_n import run_gbn_bidirectional



class GoBackNUI(ProtocolPlugin):
    name = "Go-Back-N"

    def _build_controls(self):
        row = ttk.Frame(self); row.pack(fill="x", padx=6, pady=6)
        ttk.Label(row, text="Ventana N:").pack(side="left")
        self.n_spin = ttk.Spinbox(row, from_=1, to=64, width=6); self.n_spin.set("4")
        self.n_spin.pack(side="left", padx=6)

    def reset(self, cfg: SimConfig):
        # Parámetros adicionales requeridos
        try:
            cfg.ready_on_enable = True
            cfg.ready_delay = 0.04
        except Exception:
            setattr(cfg, "ready_on_enable", True)
            setattr(cfg, "ready_delay", 0.04)

        self.runner.build_and_bind(self.name, cfg, window_size=int(self.n_spin.get()))
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
            run_gbn_bidirectional(steps=steps, max_seq=self.runner.cfg.max_seq)
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
            if s.startswith("A>"): return "LR"  # A→B
            if s.startswith("B>"): return "RL"  # B→A
        if k == "ACK":
            if "ACK:A" in s: return "LR"  # A→B
            if "ACK:B" in s: return "RL"  # B→A
        return default

    def direction_for(self, kind: str, seq: int, ack, info=None) -> str:
        # Deducción robusta desde el 'info'
        return self._dir_from_info(kind, info, default="LR")