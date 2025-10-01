# GUI/plugins/stop_and_wait_ui.py
from __future__ import annotations
from tkinter import ttk, messagebox
from Simulator.config import SimConfig
from GUI.protocol_base import ProtocolPlugin
from Protocols.Stop_and_wait.Stop_and_wait import sender_sw, receiver_sw



class StopAndWaitUI(ProtocolPlugin):
    name = "Stop-and-Wait"

    def _build_controls(self):
        row = ttk.Frame(self); row.pack(fill="x", padx=6, pady=6)
        ttk.Label(row, text="(Unidireccional A→B, ACK puro B→A, 1-bit)").pack(side="left")

    def reset(self, cfg: SimConfig):
        """
        Forzamos 1-bit de secuencia. Este era el motivo por el que veías
        siempre seq=0 / ack=0 en la tabla.
        """
        cfg.max_seq = 1
        cfg.nr_bufs = 1
        # Stop-and-Wait sin errores (la GUI principal ya lo hace; redundante pero seguro)
        cfg.loss_prob = 0.0
        cfg.corrupt_prob = 0.0

        self.runner.build_and_bind(self.name, cfg, window_size=1)
        self.anim.clear_packets()

    # Algunas bases piden 'tick'. Lo implementamos delegando a auto_step.
    def tick(self, k: int) -> int:
        total = 0
        k = max(1, int(k))
        for _ in range(k):
            total += self.auto_step()
        return total

    def auto_step(self) -> int:
        """
        Avanza en un bloque pequeño reentrante. Cada iteración ejecuta emisor y
        receptor una vez (steps=1), lo que produce DATA y ACK con seq/ack {0,1}.
        """
        try:
            BLOCK = 200  # tamaño razonable para generar progreso sin bloquear UI
            for _ in range(BLOCK):
                sender_sw(steps=1)    # A envía DATA / retransmite según timeout
                receiver_sw(steps=1)  # B procesa DATA y genera ACK
            return BLOCK
        except Exception as e:
            messagebox.showerror(self.name, str(e))
            return 0

    def direction_for(self, kind: str, seq, ack, info=None) -> str:
        """
        DATA viaja A→B (LR), ACK puro regresa B→A (RL).
        """
        return "LR" if str(kind).upper() == "DATA" else "RL"