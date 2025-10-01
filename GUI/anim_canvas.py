from __future__ import annotations
import time
import tkinter as tk
from typing import Callable, Optional, Dict, Any


class AnimationCanvas(tk.Canvas):
    """
    Canvas de animación:
      - Dibuja 2 endpoints (computadoras o nidos) y el enlace.
      - Anima UNA trama por llamada a `enqueue(...)`.
      - Soporta pausa/reanudar a mitad de vuelo (congelando la paloma).
      - Permite clickear el paquete en PAUSA para ver la metadata.
      - Usa palomas emoji: blanca (DATA) y azul (ACK).
      - Llama a un callback cuando termina una animación, para encadenar el siguiente frame.
    """

    def __init__(self, master, height=240, use_nests: bool = False):
        super().__init__(master, height=height, background="#0b1220", highlightthickness=0)
        self.pack_propagate(False)

        # ---------- Opciones visuales ----------
        # Si quieres nidos en vez de computadoras, pásalo a True (o crea con use_nests=True desde main_gui)
        self._use_nests = use_nests

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

        # Dibujo base
        self._draw_topology()

        # Click
        self.bind("<Button-1>", self._on_click)

    # ------------------ Topología (computadoras o nidos) ------------------
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

        if self._use_nests:
            # Nidos (emoji 🪺) como endpoints
            self._draw_nest(ax + 20, ay - 10, label="A")
            self._draw_nest(bx - 60, by - 10, label="B")
        else:
            # PCs (monitor + base)
            self._draw_pc(ax - 35, ay - 45, label="A")
            self._draw_pc(bx - 105, by - 45, label="B")

    def _draw_pc(self, x: int, y: int, label: str):
        """Dibuja un 'monitor' con base para la computadora."""
        # Monitor
        self.create_rectangle(x, y, x + 110, y + 70, fill="#111827", outline="#64748b", width=2, tags=("static",))
        self.create_rectangle(x + 8, y + 8, x + 102, y + 52, fill="#0b1220", outline="#1f2937", width=1, tags=("static",))
        # Base
        self.create_rectangle(x + 35, y + 72, x + 75, y + 78, fill="#1f2937", outline="#334155", width=2, tags=("static",))
        self.create_rectangle(x + 25, y + 78, x + 85, y + 86, fill="#0f172a", outline="#334155", width=2, tags=("static",))
        # Label
        self.create_text(x + 55, y + 92, text=label, fill="#e2e8f0", font=("TkDefaultFont", 12, "bold"), tags=("static",))

    def _draw_nest(self, x: int, y: int, label: str):
        """Dibuja un nido emoji (🪺) con etiqueta."""
        # Emoji de nido; si no lo renderiza tu fuente, se verá un rectángulo vacío.
        self.create_text(x + 32, y + 24, text="🪺", fill="#e2e8f0", font=("Arial", 28), tags=("static",))
        self.create_text(x + 32, y + 58, text=label, fill="#e2e8f0", font=("TkDefaultFont", 12, "bold"), tags=("static",))

    # ------------------ API pública ------------------
    def bind_click(self, cb: Callable[[dict | None], None]):
        self._click_cb = cb

    def set_on_finished(self, cb: Optional[Callable[[], None]]):
        """Callback que se invoca cuando termina de animarse el paquete actual."""
        self._finished_cb = cb

    def clear_packets(self):
        # Borra cualquier paquete en vuelo y re-dibuja la topología
        if self._tick_job:
            try:
                self.after_cancel(self._tick_job)
            except Exception:
                pass
            self._tick_job = None
        self._active = None
        self._paused = False
        self._draw_topology()

    def set_running(self, running: bool):
        # Compatibilidad con llamadas existentes
        if running:
            self.resume()
        else:
            self.pause()

    def pause(self):
        """Pausa la animación a mitad de vuelo (si hay trama activa)."""
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

    def resume(self):
        """Reanuda la animación desde donde quedó."""
        if not self._paused:
            return
        self._paused = False
        if self._active:
            self._active["t0"] = time.perf_counter()
            self._schedule_tick()

    # ------------------ Encolar y animar una trama ------------------
    def enqueue(self, kind: str, direction: str, label: str, meta: dict,
                duration_ms: int = 900):
        """
        Crea y anima UNA trama. El GUI principal encadena con set_on_finished().
        - kind: "DATA" o "ACK"
        - direction: "LR" (A->B) o "RL" (B->A)
        - label: texto (p.ej. "A>MSG_1" o "ACK:B")
        - meta: dict con t/kind/seq/ack/info (se devuelve al hacer click)
        """
        # Si había una en vuelo, la cancelamos limpiamente
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

        # Ícono (paloma emoji): DATA blanca, ACK azul
        dove = "🕊️"   # paloma
        # En muchas fuentes emoji, el color no se puede forzar; usamos dos capas de texto para contraste
        # y un "matiz" diferente (blanco vs azul) mediante el fill del texto. Si tu sistema no aplica
        # el fill al emoji, igualmente verás palomas de colores del sistema (está OK).
        fill = "#ffffff" if kind.upper() == "DATA" else "#93c5fd"
        shadow = self.create_text(x0 + 1, y + 1, text=dove, fill="#000000", font=("Arial", 18), tags=("pkt",))
        icon = self.create_text(x0, y, text=dove, fill=fill, font=("Arial", 18, "bold"), tags=("pkt",))
        # Texto de etiqueta arriba (A>MSG_1, ACK:B, etc.)
        text = self.create_text(x0, y - 18, text=str(label), fill="#e2e8f0", font=("TkDefaultFont", 9), tags=("pkt",))

        self._active = {
            "kind": kind, "dir": direction, "label": label, "meta": meta,
            "icon": icon, "shadow": shadow, "text": text,
            "x0": x0, "x1": x1, "y": y,
            "dur": max(50, int(duration_ms)),
            "t0": time.perf_counter(),
            "elapsed": 0.0,  # tiempo acumulado (para pausa)
        }

        self._schedule_tick()

    # ------------------ Loop interno de animación ------------------
    def _schedule_tick(self):
        # ~60 FPS
        self._tick_job = self.after(16, self._tick)

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
            # Fin de la trama: borrar y notificar
            self._erase_active()
            self._active = None
            if self._finished_cb:
                self._finished_cb()
            return

        self._schedule_tick()

    def _erase_active(self):
        """Elimina los elementos gráficos del paquete activo (si existen)."""
        act = self._active
        if not act:
            return
        for obj in (act.get("shadow"), act.get("icon"), act.get("text")):
            try:
                if obj:
                    self.delete(obj)
            except Exception:
                pass

    # ------------------ Click de inspección ------------------
    def _on_click(self, ev):
        # Sólo si hay algo activo; se recomienda usarlo en pausa
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