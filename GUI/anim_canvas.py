from __future__ import annotations
import time
import tkinter as tk
from typing import Callable, Optional, Dict, Any

"""
    Clase AnimationCanvas
    ---------------------------------------
    Un lienzo Tkinter para animar el envío de paquetes entre dos nodos (A y B).
"""
class AnimationCanvas(tk.Canvas):

    """
        Funcion que inicializa el lienzo de animación.
        Args:
            master: El widget padre.
            height: La altura del lienzo (por defecto 240).
    """
    def __init__(self, master, height=240):
        super().__init__(master, height=height, background="#0b1220", highlightthickness=0)
        self.pack_propagate(False)

        # Geometría
        self._pad_x = 48
        self._center_y = height // 2
        self._link_y = self._center_y + 22

        # Estado de animación
        self._active: Optional[Dict[str, Any]] = None
        self._paused: bool = False
        self._tick_job: Optional[str] = None
        self._click_cb: Optional[Callable[[dict | None], None]] = None
        self._finished_cb: Optional[Callable[[], None]] = None


        self._draw_topology()


        self.bind("<Button-1>", self._on_click)

    """
        Funcion que dibuja la topología de red en el lienzo.
        Dibuja dos nodos (A y B) y un enlace entre ellos.
        
    """
    def _draw_topology(self):
        self.delete("all")
        w = max(self.winfo_reqwidth(), self.winfo_width(), 800)
        h = max(self.winfo_reqheight(), self.winfo_height(), 240)
        self.configure(width=w, height=h)

        self._center_y = h // 2
        self._link_y = self._center_y + 22
        ax, ay = self._pad_x, self._center_y
        bx, by = w - self._pad_x, self._center_y

        # Enlace
        self.create_line(ax + 70, self._link_y, bx - 70, self._link_y, fill="#334155", width=3, tags=("static",))
        # PCs (monitor + base)
        self._draw_pc(ax - 35, ay - 45, label="A")
        self._draw_pc(bx - 105, by - 45, label="B")

    """
        Funcion que dibuja una computadora en el lienzo.
        Args:
            x: La coordenada x del monitor.
            y: La coordenada y del monitor.
            label: La etiqueta del nodo (A o B).    
        Returns:
            None
    """
    def _draw_pc(self, x, y, label):

        # Monitor
        self.create_rectangle(x, y, x + 110, y + 70, fill="#111827", outline="#64748b", width=2, tags=("static",))
        self.create_rectangle(x + 8, y + 8, x + 102, y + 52, fill="#0b1220", outline="#1f2937", width=1, tags=("static",))
        # Base
        self.create_rectangle(x + 35, y + 72, x + 75, y + 78, fill="#1f2937", outline="#334155", width=2, tags=("static",))
        self.create_rectangle(x + 25, y + 78, x + 85, y + 86, fill="#0f172a", outline="#334155", width=2, tags=("static",))
        # Label
        self.create_text(x + 55, y + 92, text=label, fill="#e2e8f0", font=("TkDefaultFont", 12, "bold"), tags=("static",))

    """
        Funcion que enlaza una función de callback al evento de clic en el lienzo.
        Args:
            cb: La función de callback que se invoca al hacer clic en un paquete.
        Returns:
            None
    """
    def bind_click(self, cb):
        self._click_cb = cb

    """
        Funcion que establece una función de callback que se invoca cuando una animación de paquete termina.
        Args:
            cb: La función de callback que se invoca al terminar la animación.
        Returns:
            None
    """
    def set_on_finished(self, cb):

        self._finished_cb = cb

    """
        Funcion que borra cualquier paquete en vuelo y re-dibuja la topología.
        Returns:
            None
    """
    def clear_packets(self):

        if self._tick_job:
            try:
                self.after_cancel(self._tick_job)
            except Exception:
                pass
            self._tick_job = None
        self._active = None
        self._paused = False
        self._draw_topology()

    """
        Funcion que establece si la animación está en ejecución o en pausa.
        Args:
            running: True para reanudar, False para pausar.
        Returns:
            None
    """
    def set_running(self, running):

        if running:
            self.resume()
        else:
            self.pause()

    """
        Funcion que pausa la animación.
    """
    def pause(self):

        if self._paused:
            return
        self._paused = True
        if self._active:
            now = time.perf_counter()
            self._active["elapsed"] += max(0.0, now - self._active["t0"])
        if self._tick_job:
            try:
                self.after_cancel(self._tick_job)
            except Exception:
                pass
            self._tick_job = None

    """
        Funcion que reanuda la animación.
    """
    def resume(self):

        if not self._paused:
            return
        self._paused = False
        if self._active:
            self._active["t0"] = time.perf_counter()
            self._schedule_tick()

    """
        Funcion que encola y anima una trama (paquete) en el lienzo.
        Args:
            kind: El tipo de trama ("DATA" o "ACK").
            direction: La dirección de la trama ("LR" para A->B o "RL" para B->A).
            label: La etiqueta de la trama (p.ej. "A>MSG_1" o "ACK:B").
            meta: Un diccionario con metadatos (t/kind/seq/ack/info) que se devuelve al hacer clic.
            duration_ms: La duración de la animación en milisegundos (por defecto 900).
        Returns:
            None
    """
    def enqueue(self, kind, direction, label, meta,
                duration_ms: int = 900):

        if self._tick_job:
            try:
                self.after_cancel(self._tick_job)
            except Exception:
                pass
            self._tick_job = None
        if self._active:
            self._erase_active()

        self._active = None
        self._paused = False

        # Geometría de la ruta
        w = max(self.winfo_reqwidth(), self.winfo_width(), 800)
        ax = self._pad_x + 70
        bx = w - self._pad_x - 70
        if direction.upper() == "LR":
            x0, x1 = ax, bx
        else:
            x0, x1 = bx, ax
        y = self._link_y

        dove = "🕊️️"

        fill = "#ffffff" if kind.upper() == "DATA" else "#93c5fd"
        shadow = self.create_text(x0 + 1, y + 1, text=dove, fill="#000000", font=("Arial", 18), tags=("pkt",))
        icon = self.create_text(x0, y, text=dove, fill=fill, font=("Arial", 18, "bold"), tags=("pkt",))

        text = self.create_text(x0, y - 18, text=str(label), fill="#e2e8f0", font=("TkDefaultFont", 9), tags=("pkt",))

        self._active = {
            "kind": kind, "dir": direction, "label": label, "meta": meta,
            "icon": icon, "shadow": shadow, "text": text,
            "x0": x0, "x1": x1, "y": y,
            "dur": max(50, int(duration_ms)),
            "t0": time.perf_counter(),
            "elapsed": 0.0,
        }

        self._schedule_tick()

    """
        Funcion que programa el siguiente tick de la animación.
        Se llama a sí misma hasta que la animación termina o se pausa.
    """
    def _schedule_tick(self):
        self._tick_job = self.after(16, self._tick)

    """
        Funcion que actualiza la posición del paquete en la animación.
        Calcula el progreso basado en el tiempo transcurrido y mueve los elementos gráficos.
        Si la animación ha terminado, borra los elementos y llama al callback de finalización
    """
    def _tick(self):
        self._tick_job = None
        act = self._active
        if not act or self._paused:
            return

        now = time.perf_counter()
        elapsed = act["elapsed"] + max(0.0, now - act["t0"])
        dur_s = act["dur"] / 1000.0
        p = 1.0 if dur_s <= 0 else min(1.0, elapsed / dur_s)

        x = act["x0"] + (act["x1"] - act["x0"]) * p
        y = act["y"]

        # Mover ícono y texto
        self.coords(act["shadow"], x + 1, y + 1)
        self.coords(act["icon"], x, y)
        self.coords(act["text"], x, y - 18)

        if p >= 1.0:

            self._erase_active()
            self._active = None
            if self._finished_cb:
                self._finished_cb()
            return

        self._schedule_tick()

    """
        Funcion que borra los elementos gráficos del paquete activo.
    """
    def _erase_active(self):

        act = self._active
        if not act:
            return
        for obj in (act.get("shadow"), act.get("icon"), act.get("text")):
            try:
                if obj:
                    self.delete(obj)
            except Exception:
                pass

    """
        Funcion que maneja el evento de clic en el lienzo.
        Si se hace clic en un paquete activo, invoca el callback registrado con los metadatos del paquete.
        Args:
            ev: El evento de clic de Tkinter.
        Returns:
            None
    """
    def _on_click(self, ev):

        if not self._active:
            return
        ids = self.find_overlapping(ev.x - 2, ev.y - 2, ev.x + 2, ev.y + 2)
        hit = False
        for obj in ids:
            if "pkt" in self.gettags(obj):
                hit = True
                break
        if hit and self._click_cb:
            self._click_cb(self._active.get("meta", {}))