from __future__ import annotations
from tkinter import ttk, messagebox
from Simulator.config import SimConfig
from Protocols.Go_back_n.Go_back_n import run_gbn_bidirectional
from GUI.protocol_base import ProtocolPlugin

def _norm_kind(kind: str) -> str:
    k = (kind or "").upper()
    if "DATA" in k: return "DATA"
    if "ACK"  in k: return "ACK"
    return kind or "?"

class GoBackNUI(ProtocolPlugin):
    name = "Go-Back-N"

    def _build_controls(self):
        row = ttk.Frame(self); row.pack(fill="x", padx=6, pady=6)
        ttk.Label(row, text="Ventana N:").pack(side="left")
        self.n_spin = ttk.Spinbox(row, from_=1, to=64, width=6)
        self.n_spin.set("4")
        self.n_spin.pack(side="left", padx=6)

    def reset(self, cfg: SimConfig):
        self.runner.build_and_bind(self.name, cfg, window_size=int(self.n_spin.get()))
        if self.anim:
            self.anim.clear_packets()

    def tick(self, k: int) -> int:
        """No se usa en el flujo actual, pero lo dejamos por compatibilidad."""
        try:
            for _ in range(k):
                run_gbn_bidirectional(steps=1, max_seq=self.runner.cfg.max_seq)
            return k
        except Exception as e:
            messagebox.showerror(self.name, str(e))
            return 0

    def auto_step(self) -> int:
        """
        Ejecuta un bloque “grande” para avanzar más rápido en la fase de generación.
        Devuelve la cantidad de steps ejecutados (aprox).
        """
        try:
            BLOCK = 100  # puedes ajustar este tamaño sin problemas
            run_gbn_bidirectional(steps=BLOCK, max_seq=self.runner.cfg.max_seq)
            return BLOCK
        except Exception as e:
            messagebox.showerror(self.name, str(e))
            return 0

    def direction_for(self, kind: str, seq: int, ack, info: str) -> str:
        """
        DATA: usa el prefijo del info ("A>" o "B>").
        ACK : "ACK:A" = A→B (LR), "ACK:B" = B→A (RL).
        """
        s = (info or "").upper()
        if _norm_kind(kind) == "DATA":
            if s.startswith("A>"): return "LR"  # A envía → izquierda a derecha
            if s.startswith("B>"): return "RL"  # B envía → derecha a izquierda
            return "LR"
        else:
            if s.startswith("ACK:A"): return "LR"  # ACK de A hacia B
            if s.startswith("ACK:B"): return "RL"  # ACK de B hacia A
            return "RL"