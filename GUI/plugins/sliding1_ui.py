from __future__ import annotations
from tkinter import ttk, messagebox
from Simulator.config import SimConfig
from GUI.protocol_base import ProtocolPlugin

# Reutilizamos la función de tu sliding window 1-bit (como en run_slidingWindow.py)
try:
    from Protocols.SlidingWindow.slidingWindow import run_gbn_bidirectional as run_sw1
except Exception:
    from slidingWindow import run_gbn_bidirectional as run_sw1


class SlidingOneBitUI(ProtocolPlugin):
    name = "Sliding Window 1-bit"

    def _build_controls(self):
        row = ttk.Frame(self); row.pack(fill="x", padx=6, pady=6)
        ttk.Label(row, text="(Full-duplex, ventana N=1)").pack(side="left")

    def reset(self, cfg: SimConfig):
        cfg.max_seq = 1
        cfg.nr_bufs = 1
        self.runner.build_and_bind(self.name, cfg, window_size=1)
        self._next_sender = "A"
        self._last_data_dir = "LR"
        self.anim.clear_packets()

    # --- compat con base (algunos proyectos piden tick) ---
    def tick(self, k: int) -> int:
        total = 0
        for _ in range(max(1, int(k))):
            total += self.auto_step()
        return total

    def auto_step(self) -> int:
        try:
            run_sw1(steps=200, max_seq=1)  # bloque razonable
            return 200
        except Exception as e:
            messagebox.showerror(self.name, str(e))
            return 0

    def direction_for(self, kind: str, seq, ack, info=None) -> str:
        # DATA alterna A→B / B→A; ACK (o piggyback) en sentido opuesto al último DATA
        if kind == "DATA":
            direction = "LR" if getattr(self, "_next_sender", "A") == "A" else "RL"
            self._last_data_dir = direction
            self._next_sender = "B" if getattr(self, "_next_sender", "A") == "A" else "A"
            return direction
        return "RL" if getattr(self, "_last_data_dir", "LR") == "LR" else "LR"