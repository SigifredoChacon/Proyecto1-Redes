# GUI/plugins/utopia_ui.py
from __future__ import annotations
from tkinter import ttk, messagebox
from Simulator.config import SimConfig
from Protocols.Utopia.utopia import sender_utopia, receive_utopia
from GUI.protocol_base import ProtocolPlugin

class UtopiaUI(ProtocolPlugin):
    name = "Utopia"

    """
        Funcion que construye los controles de la UI para Utopia
        Args:
            (ninguno): Usa self como contenedor de widgets
        Returns:
            None: Agrega una etiqueta informativa indicando que es un canal sin errores
    """
    def _build_controls(self):
        ttk.Label(self, text="Utopía sin errores.").pack(anchor="w", padx=6, pady=6)

    """
        Funcion que reinicia y configura la simulacion Utopia
        Args:
            cfg (SimConfig): Configuracion de la simulacion, se fuerzan loss_prob y corrupt_prob a 0.0
        Returns:
            None: Construye y vincula el runner con ventana 1 y limpia la animacion
    """
    def reset(self, cfg):
        cfg.loss_prob = 0.0
        cfg.corrupt_prob = 0.0
        self.runner.build_and_bind(self.name, cfg, window_size=1)
        self.anim.clear_packets()


    """
        Funcion que ejecuta k pasos de la simulacion Utopia (emision y recepcion)
        Args:
            k (int): Numero de iteraciones a avanzar; en cada una se llama a sender_utopia y receive_utopia
        Returns:
            int: Cantidad de pasos efectivamente ejecutados; 0 si hubo error (y se muestra un messagebox)
    """
    def tick(self, k):
        try:
            for _ in range(k):
                sender_utopia(steps=1)
                receive_utopia(steps=1)
            return k
        except Exception as e:
            messagebox.showerror(self.name, str(e))
            return 0

    """
        Funcion que avanza automaticamente un paso de simulacion
        Args:
            (ninguno)
        Returns:
            int: Siempre 1 si el paso se ejecuto correctamente; 0 en caso de error interno
    """
    def auto_step(self):
        return self.tick(1)

    """
        Funcion que determina la direccion de animacion para un frame
        Args:
            kind (str): Tipo de frame ("DATA" o "ACK")
            seq (int): Numero de secuencia (no utilizado para la direccion)
            ack (int): Numero de ACK (no utilizado para la direccion)
            info (str|None): Informacion adicional (no utilizada aqui)
        Returns:
            str: "LR" para DATA (izquierda, derecha) y "RL" para otros tipos (derecha, izquierda)
    """
    def direction_for(self, kind, seq, ack, info):
        return "LR" if kind == "DATA" else "RL"