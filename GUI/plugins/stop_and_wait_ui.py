from __future__ import annotations
from tkinter import ttk, messagebox
from Simulator.config import SimConfig
from GUI.protocol_base import ProtocolPlugin
from Protocols.Stop_and_wait.Stop_and_wait import sender_sw, receiver_sw


"""
    Clase GUI para el protocolo Stop-and-Wait.
    - Unidireccional A→B (DATA), ACK B→A.
    - 1-bit de secuencia (0/1).
    - Canal perfecto (sin pérdidas ni corrupción).
"""
class StopAndWaitUI(ProtocolPlugin):
    name = "Stop-and-Wait"

    """
        Función interna que construye los controles específicos del protocolo.
        Args:
            self: instancia del plugin.
        Returns:
            None
    """
    def _build_controls(self):
        row = ttk.Frame(self)
        row.pack(fill="x", padx=6, pady=6)
        ttk.Label(row, text="(Unidireccional A→B, ACK B→A, 1-bit)").pack(side="left")


    """
        Funcion que resetea el estado del plugin y crea/bindea un Engine nuevo con la configuración dada.
        Args:
            cfg (SimConfig): configuración de la simulación.
        Returns:
            None
    """
    def reset(self, cfg):

        cfg.max_seq = 1
        cfg.nr_bufs = 1
        cfg.loss_prob = 0.0
        cfg.corrupt_prob = 0.0
        cfg.jitter = 0.1
        cfg.data_timeout = 0.25
        cfg.ack_timeout = 0.08

        self.runner.build_and_bind(self.name, cfg, window_size=1)
        self.anim.clear_packets()

    """
        Función que avanza la simulación k pasos.
        Args:
            k (int): número de pasos a avanzar.
        Returns:
            int: cantidad de pasos ejecutados.
    """
    def tick(self, k):
        total = 0
        k = max(1, int(k))
        for _ in range(k):
            total += self.auto_step()
        return total

    """
        Función que avanza en modo automático.
        Returns:
            int: cantidad de pasos ejecutados en este ciclo.
    """
    def auto_step(self):

        BLOCK = 200
        processed = 0

        for _ in range(BLOCK):
            try:
                sender_sw(steps=1)
            except IndexError:
                break
            except Exception as e:
                messagebox.showerror(self.name, str(e))
                return processed

            try:
                receiver_sw(steps=1)
            except IndexError:
                break
            except Exception as e:
                messagebox.showerror(self.name, str(e))
                return processed

            processed += 1

        return processed

    """
        Función que decide la dirección de animación para una trama.
        Args:
            kind (str): tipo de trama ("DATA" o "ACK").
            seq (int): número de secuencia de la trama.
            ack (int): número de acuse de la trama.
            info (str): información adicional de la trama.
        Returns:
            str: "LR" (A→B) o "RL" (B→A).
    """
    def direction_for(self, kind, seq, ack, info):

        if str(kind) == "DATA":
            return "LR"
        else:
            return "RL"