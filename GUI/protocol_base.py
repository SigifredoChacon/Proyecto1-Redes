# GUI/protocol_base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from tkinter import ttk
from typing import Callable, Optional
from Simulator.config import SimConfig

class ProtocolPlugin(ABC, ttk.Frame):
    """
    Base para plugins de protocolos.
    El método auto_step() DEBE devolver la cantidad de steps ejecutados en ese ciclo,
    para que el Main pueda cortar al llegar al límite configurado por el usuario.
    """
    name: str = "Base"

    def __init__(self, master):
        super().__init__(master)
        self.runner = None              # lo inyecta el Main (wrapper del Engine)
        self.anim = None                # AnimationCanvas compartido
        self.on_refresh: Optional[Callable[[], None]] = None  # callback del Main
        self._build_controls()

    def bind_host(self, runner, anim, on_refresh: Callable[[], None]):
        """El Main llama a esto para enlazar el plugin con el host/canvas."""
        self.runner = runner
        self.anim = anim
        self.on_refresh = on_refresh

    # ---------- Métodos que debe implementar cada plugin ----------

    @abstractmethod
    def _build_controls(self) -> None:
        """Construye y monta los controles específicos del protocolo en este frame."""
        raise NotImplementedError

    @abstractmethod
    def reset(self, cfg: SimConfig) -> None:
        """Crea/bindea un Engine nuevo con 'cfg' y deja listo el estado del plugin."""
        raise NotImplementedError

    @abstractmethod
    def tick(self, k: int) -> int:
        """
        Avanza la simulación k pasos (si el plugin lo usa).
        Debe devolver cuántos steps ejecutó (int).
        """
        raise NotImplementedError

    @abstractmethod
    def auto_step(self) -> int:
        """
        Avanza en modo automático (el Main lo invoca en bucle).
        Debe devolver cuántos steps ejecutó en este ciclo (int).
        """
        raise NotImplementedError

    @abstractmethod
    def direction_for(self, kind: str, seq: int, ack, info: str) -> str:
        """
        Decide la dirección de animación para una trama.
        kind: "DATA"/"ACK" normalizado
        Debe devolver "LR" (A→B) o "RL" (B→A)
        """
        raise NotImplementedError