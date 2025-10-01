# GUI/plugins/utopia_ui.py
from __future__ import annotations
from tkinter import ttk, messagebox
from Simulator.config import SimConfig
from Protocols.Utopia.utopia import sender_utopia, receive_utopia
from GUI.protocol_base import ProtocolPlugin

class UtopiaUI(ProtocolPlugin):
    name = "Utopia"

    def _build_controls(self):
        ttk.Label(self, text="Utopía sin errores (unidireccional).").pack(anchor="w", padx=6, pady=6)

    def reset(self, cfg: SimConfig):
        cfg.loss_prob = 0.0; cfg.corrupt_prob = 0.0
        self.runner.build_and_bind(self.name, cfg, window_size=1)
        self.anim.clear_packets()

    def tick(self, k: int) -> int:
        try:
            for _ in range(k):
                sender_utopia(steps=1); receive_utopia(steps=1)
            return k
        except Exception as e:
            messagebox.showerror(self.name, str(e))
            return 0

    def auto_step(self) -> int:
        # 1 step por ciclo; el Main corta al llegar al límite
        return self.tick(1)

    def direction_for(self, kind: str, seq: int, ack, info: str) -> str:
        return "LR" if kind == "DATA" else "RL"