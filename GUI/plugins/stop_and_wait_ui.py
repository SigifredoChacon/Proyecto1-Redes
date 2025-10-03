# GUI/plugins/stop_and_wait_ui.py
from __future__ import annotations
from tkinter import ttk, messagebox
from Simulator.config import SimConfig
from GUI.protocol_base import ProtocolPlugin

# Import según tu repo (3 rutas contempladas)
from Protocols.Stop_and_wait.Stop_and_wait import sender_sw, receiver_sw



class StopAndWaitUI(ProtocolPlugin):
    """
    Stop-and-Wait (ABP) unidireccional:
    - DATA A->B con bit de secuencia alternante (0/1)
    - ACK puro B->A con ack = seq recibido
    - Retransmisión por TIMEOUT (gestionado dentro del protocolo)
    """
    name = "Stop-and-Wait"

    # ---------- Controles específicos ----------
    def _build_controls(self):
        row = ttk.Frame(self)
        row.pack(fill="x", padx=6, pady=6)
        ttk.Label(row, text="(Unidireccional A→B, ACK B→A, 1-bit)").pack(side="left")

    # ---------- Ciclo de vida ----------
    def reset(self, cfg: SimConfig):
        """
        Forzamos 1-bit de secuencia (ABP) y canal perfecto según la guía.
        El Main GUI ya bloquea pérdidas/corrupción para S&W y Utopía,
        pero lo dejamos aquí por seguridad.
        """
        cfg.max_seq = 1
        cfg.nr_bufs = 1
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
        Avanza la simulación en un bloque pequeño y reentrante.
        Cada iteración llama emisor y receptor una vez (steps=1).
        Manejo robusto de cola vacía (IndexError) sin mostrar popups.
        """
        BLOCK = 200  # tamaño de bloque razonable
        processed = 0

        # Nota: algunos Engines pueden lanzar IndexError si la cola está vacía.
        # Lo tratamos como 'idle' y devolvemos lo procesado hasta ahora.
        for _ in range(BLOCK):
            try:
                sender_sw(steps=1)    # A envía / retransmite según timeout
            except IndexError:
                # cola vacía en emisor: estado ocioso en este instante
                break
            except Exception as e:
                # Errores reales del protocolo sí deben mostrarse
                messagebox.showerror(self.name, str(e))
                return processed

            try:
                receiver_sw(steps=1)  # B procesa y envía ACK correspondiente
            except IndexError:
                # cola vacía en receptor (nada que procesar ahora mismo)
                break
            except Exception as e:
                messagebox.showerror(self.name, str(e))
                return processed

            processed += 1

        return processed

    # ---------- Dirección para la animación ----------
    def direction_for(self, kind: str, seq, ack, info=None) -> str:
        """
        DATA viaja A→B (LR); ACK puro regresa B→A (RL).
        """
        return "LR" if str(kind).upper() == "DATA" else "RL"