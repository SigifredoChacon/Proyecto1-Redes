from __future__ import annotations
from abc import ABC, abstractmethod
from tkinter import ttk
from typing import Callable, Optional
from Simulator.config import SimConfig

"""
    Clase base para plugins de protocolos.
    Cada protocolo debe implementar una subclase de esta.
"""
class ProtocolPlugin(ABC, ttk.Frame):

    name: str = "Base"

    """
        Contiene los controles específicos del protocolo.
        El Main lo crea y lo monta en su GUI.
    """
    def __init__(self, master):
        super().__init__(master)
        self.runner = None
        self.anim = None
        self.on_refresh: Optional[Callable[[], None]] = None
        self._build_controls()

    """
        Fija referencias al Runner, Anim y función de refresco.
        Lo llama el Main al crear el plugin.
    """
    def bind_host(self, runner, anim, on_refresh: Callable[[], None]):

        self.runner = runner
        self.anim = anim
        self.on_refresh = on_refresh

    """
        Funciones abstractas que cada plugin debe implementar.
    """

    @abstractmethod
    def _build_controls(self) -> None:

        raise NotImplementedError

    @abstractmethod
    def reset(self, cfg: SimConfig) -> None:

        raise NotImplementedError

    @abstractmethod
    def tick(self, k: int) -> int:

        raise NotImplementedError

    @abstractmethod
    def auto_step(self) -> int:

        raise NotImplementedError

    @abstractmethod
    def direction_for(self, kind: str, seq: int, ack, info: str) -> str:

        raise NotImplementedError