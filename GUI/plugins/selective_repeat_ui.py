# GUI/plugins/selective_repeat_ui.py
from __future__ import annotations
from tkinter import ttk, messagebox
from Simulator.config import SimConfig
from GUI.protocol_base import ProtocolPlugin

# Ruta principal y fallback
from Protocols.SelectiveRepeat.selectiveRepeat import run_sr_bidirectional



class SelectiveRepeatUI(ProtocolPlugin):
    name = "Selective Repeat"

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
            # Si SimConfig no tiene esos campos, se agregan dinámicamente
            setattr(cfg, "ready_on_enable", True)
            setattr(cfg, "ready_delay", 0.04)

        self.runner.build_and_bind(self.name, cfg, window_size=int(self.n_spin.get()))
        self._ran_full = False   # control: correr 2000 una sola vez
        self._next_sender = "A"
        self._last_data_dir = "LR"
        self.anim.clear_packets()

    # compat opcional con base
    def tick(self, k: int) -> int:
        return self.auto_step()

    def auto_step(self) -> int:
        """
        Requisito: correr 2000 steps de una sola vez (no en bloques).
        Solo la primera vez devuelve 2000; luego 0.
        """
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

    def direction_for(self, kind: str, seq: int, ack, info=None) -> str:
        # DATA alterna A->B y B->A; ACK en sentido opuesto al último DATA
        if kind == "DATA":
            direction = "LR" if getattr(self, "_next_sender", "A") == "A" else "RL"
            self._last_data_dir = direction
            self._next_sender = "B" if getattr(self, "_next_sender", "A") == "A" else "A"
            return direction
        return "RL" if getattr(self, "_last_data_dir", "LR") == "LR" else "LR"