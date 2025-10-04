# GUI/main_gui.py
from __future__ import annotations
import sys, os
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, List, Any

# ----- Rutas del proyecto -----
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.append(BASE)

from Simulator.config import SimConfig
from Simulator.engine import Engine
from Events.api import bind

from GUI.anim_canvas import AnimationCanvas
from GUI.plugins.utopia_ui import UtopiaUI
from GUI.plugins.stop_and_wait_ui import StopAndWaitUI
from GUI.plugins.gobackn_ui import GoBackNUI
from GUI.plugins.selective_repeat_ui import SelectiveRepeatUI
from GUI.plugins.par_ui import PARUI
from GUI.plugins.sliding1_ui import SlidingOneBitUI
from GUI.protocol_base import ProtocolPlugin


# ---------- util: normalización de filas TX ----------
def _norm_kind(kind: str) -> str:
    k = (kind or "").upper()
    if "DATA" in k: return "DATA"
    if "ACK"  in k: return "ACK"
    return kind or "?"

def _is_int_like(x: Any) -> bool:
    return isinstance(x, int) or (isinstance(x, float) and float(x).is_integer())

def _parse_tx_row(row: Any):
    # Soporta Engine.snapshot(): ("tx": [(t, kind, seq, ack, info), ...])
    if isinstance(row, dict):
        t = float(row.get("t", row.get("time", 0.0)) or 0.0)
        kind = str(row.get("kind", row.get("type", "DATA")) or "DATA")
        seq = row.get("seq", None)
        ack = row.get("ack", None)
        info = row.get("info", "")
        seq = int(seq) if _is_int_like(seq) else (None if seq is None else seq)
        ack = int(ack) if _is_int_like(ack) else (None if ack is None else ack)
        info = str(info or "")
        return t, kind, seq, ack, info

    if isinstance(row, (list, tuple)):
        vals = list(row) + [None] * (5 - len(row))
        t, kind, a, b, c = vals[:5]
        t = float(t or 0.0); kind = str(kind or "DATA")
        # (t, kind, seq, ack, info)
        if _is_int_like(a) and (_is_int_like(b) or b is None) and isinstance(c, (str, type(None))):
            seq = int(a); ack = int(b) if _is_int_like(b) else (None if b is None else b)
            info = "" if c is None else str(c)
            return t, kind, seq, ack, info
        # (t, kind, seq, info, ack)
        if _is_int_like(a) and isinstance(b, str) and (_is_int_like(c) or c is None):
            seq = int(a); info = str(b); ack = int(c) if _is_int_like(c) else (None if c is None else c)
            return t, kind, seq, ack, info
        # fallback tolerante
        seq = int(a) if _is_int_like(a) else None
        if _is_int_like(b): ack, info = int(b), str(c or "")
        elif isinstance(b, str): info, ack = str(b), (int(c) if _is_int_like(c) else None)
        else: ack, info = (int(c) if _is_int_like(c) else None), str(b or "")
        return t, kind, seq, ack, info

    return 0.0, "DATA", None, None, str(row)

def _normalize_tx_rows(rows: List[Any]):
    return [_parse_tx_row(r) for r in rows]


# ---------------- Runner (Engine + bind) ----------------
class Runner:
    def __init__(self):
        self.engine: Optional[Engine] = None
        self.cfg: Optional[SimConfig] = None
        self.protocol_name: Optional[str] = None

    def build_and_bind(self, protocol: str, cfg: SimConfig, window_size: int):
        self.protocol_name = protocol
        self.cfg = cfg
        self.engine = Engine(cfg)
        bind(self.engine)

    def snapshot(self):
        return self.engine.snapshot() if self.engine else {"time": 0.0, "tx": [], "rx": [], "events": []}


# ---------------- Main GUI ----------------
class MainGUI(ttk.Frame):
    ANIM_DURATION_MS = 2200
    ANIM_GAP_MS = 180

    def __init__(self, master):
        super().__init__(master)
        self.master = master
        self.runner = Runner()
        self.anim: AnimationCanvas | None = None
        self.plugin: ProtocolPlugin | None = None

        # estado
        self._is_running = False
        self._paused = False
        self._job = None

        # límites y contadores (NO CAMBIAR FUNCIONALIDAD)
        self._steps_done = 0
        self._min_limit_by_proto = {
            "Utopia": 10,
            "Stop-and-Wait": 10,
            "PAR": 10,
            "Sliding Window 1-bit": 2000,
            "Go-Back-N": 2000,
            "Selective Repeat": 2000,
        }
        self._target_steps = 0

        # animación por lotes
        self._last_tx_len = 0
        self._pending_anim: List[tuple] = []
        self._animating = False
        self._anim_index = 0
        self._anim_total = 0

        # fase: "idle" | "gen" | "anim"
        self._phase = "idle"

        self._setup_styles()
        self._build_layout()
        self._load_plugin("Utopia")

    # ---------- estilos (solo visual) ----------
    def _setup_styles(self):
        style = ttk.Style()
        try: style.theme_use("clam")
        except: pass

        # Paleta
        bg   = "#0b1020"  # más profundo
        card = "#111a2b"
        field= "#162841"
        fg   = "#e7edf5"
        sub  = "#9fb3c8"
        acc  = "#3b82f6"  # azul suave

        # Base
        style.configure(".", background=bg, foreground=fg, font=("Segoe UI", 10))
        self.master.configure(background=bg)

        # Cards
        style.configure("Card.TLabelframe", background=card, foreground=fg, relief="flat")
        style.configure("Card.TLabelframe.Label", font=("Segoe UI Semibold", 10), foreground=fg)
        style.map("Card.TLabelframe", background=[("active", card)])

        # Headers
        style.configure("Header.TLabel", background=bg, foreground=fg, font=("Segoe UI Semibold", 16))
        style.configure("Subheader.TLabel", background=bg, foreground=sub, font=("Segoe UI", 10))

        # Inputs
        style.configure("TEntry", fieldbackground=field, foreground=fg)
        style.configure("TCombobox", fieldbackground=field, foreground=fg, arrowsize=14)
        style.configure("TSpinbox", fieldbackground=field, foreground=fg)

        # Buttons
        style.configure("Accent.TButton",
                        background=acc, foreground="white", padding=8, anchor="center")
        style.map("Accent.TButton",
                  background=[("active", "#2563eb")], foreground=[("active", "white")])
        style.configure("TButton", padding=8)
        style.map("TButton", background=[("active", "#1f2b44")])

        # Treeview
        style.configure("Treeview",
                        background=field, fieldbackground=field, foreground=fg, rowheight=26,
                        font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background=card, foreground=fg, font=("Segoe UI Semibold", 10))

        # Listbox/Combobox popup
        root = self.master
        root.option_add("*TCombobox*Listbox*background", field)
        root.option_add("*TCombobox*Listbox*foreground", fg)
        root.option_add("*Listbox*background", field)
        root.option_add("*Listbox*foreground", fg)
        root.option_add("*Entry*foreground", fg)

        # Guardamos colores para pequeñas líneas decorativas
        self._clr = {"bg": bg, "card": card, "field": field, "fg": fg, "sub": sub, "acc": acc}

    # ---------- layout (solo visual) ----------
    def _build_layout(self):
        # Banner superior
        topbar = ttk.Frame(self, padding=(10, 12))
        topbar.pack(side="top", fill="x")
        ttk.Label(topbar, text="Simulador de Protocolos de Enlace",
                  style="Header.TLabel").pack(side="left")
        ttk.Label(topbar, text="Utopía · Stop-and-Wait · PAR · GBN · SR · SW(1-bit)",
                  style="Subheader.TLabel").pack(side="left", padx=(10,0))

        # Línea decorativa
        deco = tk.Frame(self, height=2, bg=self._clr["acc"])
        deco.pack(fill="x", padx=0, pady=(0,6))

        # Contenedor principal: columnas
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        # Sidebar izquierda
        left = ttk.Frame(body)
        left.pack(side="left", fill="y", padx=(0,10))

        # Panel derecho
        right = ttk.Frame(body)
        right.pack(side="right", fill="both", expand=True)

        # --- LEFT: tarjeta configuración ---
        cfg_card = ttk.Labelframe(left, text="Configuración", style="Card.TLabelframe", padding=10)
        cfg_card.pack(fill="x")

        # Protocolo
        row = ttk.Frame(cfg_card); row.pack(fill="x", pady=(2,8))
        ttk.Label(row, text="Protocolo").pack(anchor="w")
        self.sel_proto = ttk.Combobox(
            row, state="readonly",
            values=["Utopia", "Stop-and-Wait", "PAR", "Sliding Window 1-bit", "Go-Back-N", "Selective Repeat"]
        )
        self.sel_proto.current(0)
        self.sel_proto.pack(fill="x", pady=(4,0))
        self.sel_proto.bind("<<ComboboxSelected>>", self._on_proto_change)

        # Grid de parámetros
        self.delay = tk.DoubleVar(value=0.02)
        self.loss = tk.DoubleVar(value=0.0)
        self.corrupt = tk.DoubleVar(value=0.0)

        self.maxseq  = tk.IntVar(value=7)

        params = [
            ("Delay (s)", self.delay, 0.0, 5.0, 0.01),
            ("Pérdida (0-1)", self.loss, 0.0, 1.0, 0.01),
            ("Corrupción (0-1)", self.corrupt, 0.0, 1.0, 0.01),
            ("max_seq (2^n - 1)", self.maxseq, 1, 31, 2),
        ]

        grid = ttk.Frame(cfg_card); grid.pack(fill="x", pady=(6,8))
        for i, (lbl, var, frm, to, inc) in enumerate(params):
            r = ttk.Frame(grid)
            r.grid(row=i, column=0, sticky="ew", pady=2)
            ttk.Label(r, text=lbl).pack(side="left")
            sp = ttk.Spinbox(r, textvariable=var, from_=frm, to=to, increment=inc, width=10, justify="right")
            sp.pack(side="right")

        # Pasos
        limit_card = ttk.Labelframe(left, text="Pasos", style="Card.TLabelframe", padding=10)
        limit_card.pack(fill="x", pady=(10,0))
        lr = ttk.Frame(limit_card); lr.pack(fill="x")
        ttk.Label(lr, text="Máximo de pasos").pack(side="left")
        self.step_limit_var = tk.IntVar(value=10)
        self.step_limit = ttk.Spinbox(lr, textvariable=self.step_limit_var, from_=10, to=1000000,
                                      increment=10, width=10, justify="right")
        self.step_limit.pack(side="right")

        # Controles de animación
        ctrls = ttk.Labelframe(left, text="Animación", style="Card.TLabelframe", padding=10)
        ctrls.pack(fill="x", pady=(10,0))
        ttk.Button(ctrls, text="Inicializar / Reset", command=self._reset, style="Accent.TButton")\
            .pack(fill="x", pady=(0,8))
        self.btn_auto = ttk.Button(ctrls, text="Ejecutar", command=self._auto_start)
        self.btn_auto.pack(fill="x", pady=4)
        self.btn_pause = ttk.Button(ctrls, text="Pausa", command=self._toggle_pause)
        self.btn_pause.pack(fill="x", pady=4)
        ttk.Button(ctrls, text="Detener", command=self._auto_stop).pack(fill="x", pady=4)

        # Controles del protocolo
        self.plugin_host = ttk.Labelframe(left, text="Controles del Protocolo", style="Card.TLabelframe", padding=10)
        self.plugin_host.pack(fill="x", pady=(10,0))

        # --- RIGHT: tarjetas estado, canvas, detalle y tablas ---
        # Estado
        state = ttk.Labelframe(right, text="Estado", style="Card.TLabelframe", padding=10); state.pack(fill="x")
        sg = ttk.Frame(state); sg.pack(fill="x")
        self.time_var = tk.StringVar(value="0.00 s")
        self.tx_total_var = tk.StringVar(value="0 (DATA 0 | ACK 0)")
        self.rx_total_var = tk.StringVar(value="0")
        self.eff_var = tk.StringVar(value="0.00")
        self.gp_var = tk.StringVar(value="0.00 pkts/s")
        self._kv(sg, 0, "t (sim)", self.time_var); self._kv(sg, 0, "TX totales", self.tx_total_var, col=1)
        self._kv(sg, 1, "RX entregados", self.rx_total_var);


        # Canvas (computadoras)
        canvas_card = ttk.Labelframe(right, text="Topología / Tramas", style="Card.TLabelframe", padding=10)
        canvas_card.pack(fill="x", pady=(10,0))
        self.anim = AnimationCanvas(canvas_card, height=280, use_nests=False)
        self.anim.pack(fill="x")
        self.anim.bind_click(self._on_packet_clicked)
        self.anim.set_on_finished(self._on_anim_finished)

        # Detalle de paquete
        detail = ttk.Labelframe(right, text="Detalle del paquete (pausa + click)", style="Card.TLabelframe", padding=10)
        detail.pack(fill="x", pady=(10,0))
        dg = ttk.Frame(detail); dg.pack(fill="x")
        self.sel_t = tk.StringVar(value="-"); self.sel_kind = tk.StringVar(value="-")
        self.sel_seq = tk.StringVar(value="-"); self.sel_ack = tk.StringVar(value="-"); self.sel_info = tk.StringVar(value="-")
        self._kv(dg, 0, "t", self.sel_t); self._kv(dg, 0, "kind", self.sel_kind, col=1)
        self._kv(dg, 1, "seq", self.sel_seq); self._kv(dg, 1, "ack", self.sel_ack, col=1)
        self._kv(dg, 2, "info", self.sel_info, col=0)

        # Tablas
        tables_card = ttk.Labelframe(right, text="Historial", style="Card.TLabelframe", padding=10)
        tables_card.pack(fill="both", expand=True, pady=(10,0))
        tables = ttk.Panedwindow(tables_card, orient=tk.HORIZONTAL)
        tables.pack(fill="both", expand=True)

        self.tx_frame = ttk.Frame(tables); self.rx_frame = ttk.Frame(tables)
        tables.add(self.tx_frame, weight=3); tables.add(self.rx_frame, weight=2)

        self.tx_tree = self._build_tx_table(self.tx_frame)
        self.rx_tree = self._build_rx_table(self.rx_frame)

        # Progreso
        status = ttk.Frame(right); status.pack(fill="x", pady=(8, 0))
        self.progress_var = tk.StringVar(value="Listo")
        ttk.Label(status, textvariable=self.progress_var, anchor="e", style="Subheader.TLabel")\
            .pack(side="right")

        self.pack(fill="both", expand=True)
        self._apply_min_limit("Utopia")

    # ---------- helpers UI ----------
    def _kv(self, parent, r, k, var, col=0):
        frm = ttk.Frame(parent)
        frm.grid(row=r, column=col, sticky="ew", padx=6, pady=3)
        ttk.Label(frm, text=k + ": ").pack(side="left")
        ttk.Label(frm, textvariable=var, font=("Segoe UI Semibold", 11)).pack(side="left")

    def _build_tx_table(self, parent):
        cols = ("t", "kind", "seq", "ack", "info")
        tr = ttk.Treeview(parent, columns=cols, show="headings", height=10)
        for c, w in zip(cols, (80, 120, 60, 60, 520)):
            tr.heading(c, text=c); tr.column(c, width=w, anchor=tk.CENTER if c != "info" else tk.W)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=tr.yview)
        tr.configure(yscrollcommand=vsb.set)
        tr.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        return tr

    def _build_rx_table(self, parent):
        cols = ("t", "data")
        tr = ttk.Treeview(parent, columns=cols, show="headings", height=10)
        for c, w in zip(cols, (80, 600)):
            tr.heading(c, text=c); tr.column(c, width=w, anchor=tk.CENTER if c == "t" else tk.W)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=tr.yview)
        tr.configure(yscrollcommand=vsb.set)
        tr.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        return tr

    # ---------- plugins ----------
    def _on_proto_change(self, _evt=None):
        name = self.sel_proto.get()
        self._apply_min_limit(name)
        self._load_plugin(name)

    def _apply_min_limit(self, proto_name: str):
        minv = self._min_limit_by_proto.get(proto_name, 10)
        self.step_limit.configure(from_=minv)
        if int(self.step_limit_var.get()) < minv:
            self.step_limit_var.set(minv)

    def _load_plugin(self, name: str):
        for w in self.plugin_host.winfo_children():
            w.destroy()
        if name == "Utopia":
            self.plugin = UtopiaUI(self.plugin_host)
        elif name == "Stop-and-Wait":
            self.plugin = StopAndWaitUI(self.plugin_host)
        elif name == "PAR":
            self.plugin = PARUI(self.plugin_host)
        elif name == "Sliding Window 1-bit":
            self.plugin = SlidingOneBitUI(self.plugin_host)
        elif name == "Go-Back-N":
            self.plugin = GoBackNUI(self.plugin_host)
        elif name == "Selective Repeat":
            self.plugin = SelectiveRepeatUI(self.plugin_host)
        else:
            self.plugin = None
            messagebox.showerror("Protocolo", f"{name} no implementado")
            return

        self.plugin.pack(fill="x")
        self.plugin.bind_host(self.runner, self.anim, self._refresh)

        # Reglas del enunciado: Utopía / Stop-and-Wait sin errores en canal (visual, no funcional)
        if name in ("Utopia", "Stop-and-Wait"):
            self.loss.set(0.0); self.corrupt.set(0.0)

    def _cfg(self) -> SimConfig:
        return SimConfig(
            delay=float(self.delay.get()),
            loss_prob=float(self.loss.get()), corrupt_prob=float(self.corrupt.get()),
            max_seq=int(self.maxseq.get()), nr_bufs=(int(self.maxseq.get()) + 1) // 2,
        )

    # ---------- acciones (SIN CAMBIOS FUNCIONALES) ----------
    def _reset(self):
        self._auto_stop()
        if not self.plugin:
            return
        cfg = self._cfg()
        from GUI.plugins.stop_and_wait_ui import StopAndWaitUI as _SW
        from GUI.plugins.utopia_ui import UtopiaUI as _UT
        if isinstance(self.plugin, (_UT, _SW)):
            cfg.loss_prob = 0.0
            cfg.corrupt_prob = 0.0

        # limpiar UI
        self.anim.clear_packets()
        self.tx_tree.delete(*self.tx_tree.get_children())
        self.rx_tree.delete(*self.rx_tree.get_children())
        self.time_var.set("0.00 s"); self.tx_total_var.set("0 (DATA 0 | ACK 0)")
        self.rx_total_var.set("0"); self.eff_var.set("0.00"); self.gp_var.set("0.00 pkts/s")
        self.sel_t.set("-"); self.sel_kind.set("-"); self.sel_seq.set("-"); self.sel_ack.set("-"); self.sel_info.set("-")
        self.progress_var.set("Listo")

        # estado
        self._steps_done = 0
        self._target_steps = 0
        self._phase = "idle"
        self._last_tx_len = 0
        self._pending_anim.clear()
        self._animating = False
        self._paused = False
        self.btn_pause.configure(text="Pausa")

        self.plugin.reset(cfg)
        self.anim.set_running(False)
        self._refresh(force=True)

    def _auto_start(self):
        if self._is_running or not self.plugin:
            return
        target = int(self.step_limit_var.get())
        minv = self._min_limit_by_proto.get(self.sel_proto.get(), 10)
        if target < minv:
            target = minv
            self.step_limit_var.set(minv)
        self._target_steps = target

        self._is_running = True
        self._paused = False
        self.btn_pause.configure(text="Pausa")
        self.anim.set_running(False)
        self._start_generation_phase()

    def _auto_stop(self):
        self._is_running = False
        self._paused = False
        self.anim.set_running(False)
        self.btn_auto.configure(text="Ejecutar")
        self.btn_pause.configure(text="Pausa")
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        self._pending_anim.clear()
        self._animating = False
        self._phase = "idle"
        self.progress_var.set("Listo")

    def _toggle_pause(self):
        if not self._is_running:
            return
        self._paused = not self._paused
        if self._paused:
            self.btn_pause.configure(text="▶ Reanudar")
            self.progress_var.set("Pausado")
            self.anim.pause()
            if self._job:
                try:
                    self.after_cancel(self._job)
                except Exception:
                    pass
                self._job = None
        else:
            self.btn_pause.configure(text="⏯ Pausa")
            if self._phase == "gen":
                self.progress_var.set(f"Generando {self._steps_done}/{self._target_steps}")
                self.anim.resume()
                self._gen_loop_autostep()
            elif self._phase == "anim":
                self.progress_var.set(f"Animando {self._anim_index}/{self._anim_total}")
                self.anim.resume()

    # ---------- Fase 1: Generación ----------
    def _start_generation_phase(self):
        self._phase = "gen"
        self.progress_var.set(f"Generando 0/{self._target_steps}")
        self._gen_loop_autostep()

    def _gen_loop_autostep(self):
        if not self._is_running or self._phase != "gen" or self._paused:
            return

        if self._steps_done >= self._target_steps:
            self._refresh()
            self._prepare_anim_batch_from_delta()
            self.anim.set_running(True)
            self._start_anim_batch()
            return

        try:
            got = int(self.plugin.auto_step())
        except Exception as e:
            messagebox.showerror("Generación", f"auto_step falló: {e}")
            self._auto_stop()
            return

        if got < 0:
            got = 0
        remain = self._target_steps - self._steps_done
        use = min(got, remain)
        self._steps_done += use

        self.progress_var.set(f"Generando {self._steps_done}/{self._target_steps}")
        self._refresh()
        self._job = self.after(1, self._gen_loop_autostep)

    # ---------- Fase 2: Animación ----------
    def _prepare_anim_batch_from_delta(self):
        snap = self.runner.snapshot()
        tx_rows = _normalize_tx_rows(snap.get("tx", []))
        if len(tx_rows) <= self._last_tx_len:
            return
        for (t, kind, seq, ack, info) in tx_rows[self._last_tx_len:]:
            nk = _norm_kind(kind)
            direction = self.plugin.direction_for(nk, seq, ack, info)
            label = str(info) if info not in (None, "") else (f"D{seq}" if nk == "DATA" else f"A{ack}")
            self._pending_anim.append(
                (nk, direction, label, {"t": t, "kind": kind, "seq": seq, "ack": ack, "info": info})
            )
        self._last_tx_len = len(tx_rows)

    def _start_anim_batch(self):
        self._phase = "anim"
        if not self._pending_anim:
            self._auto_stop()
            return
        if self._paused:
            return
        self._animating = True
        self._anim_index = 1
        self._anim_total = len(self._pending_anim)
        nk, direction, label, meta = self._pending_anim.pop(0)
        self.progress_var.set(f"Animando {self._anim_index}/{self._anim_total}")
        self.anim.enqueue(nk, direction, label, meta, duration_ms=self.ANIM_DURATION_MS)

    def _on_anim_finished(self):
        if not self._is_running or self._phase != "anim":
            return
        if self._paused:
            self._animating = False
            return
        if not self._pending_anim:
            self._animating = False
            self._auto_stop()
            return
        self._anim_index += 1
        nk, direction, label, meta = self._pending_anim.pop(0)
        self.progress_var.set(f"Animando {self._anim_index}/{self._anim_total}")
        self.anim.enqueue(nk, direction, label, meta, duration_ms=self.ANIM_DURATION_MS)

    # ---------- refresco UI ----------
    def _refresh(self, force: bool=False):
        snap = self.runner.snapshot()
        raw_tx = snap.get("tx", [])
        tx_rows = _normalize_tx_rows(raw_tx)

        # TX
        self.tx_tree.delete(*self.tx_tree.get_children())
        for (t, kind, seq, ack, info) in tx_rows:
            self.tx_tree.insert("", tk.END, values=(
                f"{t:.2f}", str(kind),
                "—" if seq is None else seq,
                "—" if ack is None else ack,
                info
            ))
        # RX
        self.rx_tree.delete(*self.rx_tree.get_children())
        for it in snap.get("rx", []):
            if isinstance(it, (list, tuple)) and len(it) == 2 and isinstance(it[0], (int, float)):
                tt, data = it
            else:
                tt, data = 0.0, str(it)
            self.rx_tree.insert("", tk.END, values=(f"{tt:.2f}", str(data)))

        # métricas
        t = float(snap.get("time", 0.0))
        data_tx = [r for r in tx_rows if _norm_kind(r[1]) == "DATA"]
        ack_tx  = [r for r in tx_rows if _norm_kind(r[1]) == "ACK"]
        rx = snap.get("rx", []); rx_count = len(rx)
        self.time_var.set(f"{t:.2f} s")
        self.tx_total_var.set(f"{len(tx_rows)} (DATA {len(data_tx)} | ACK {len(ack_tx)})")
        self.rx_total_var.set(f"{rx_count}")
        eff = (rx_count / len(data_tx)) if data_tx else 0.0
        gp = (rx_count / t) if t > 0 else 0.0
        self.eff_var.set(f"{eff:.2f}"); self.gp_var.set(f"{gp:.2f} pkts/s")

        if force:
            self.anim.clear_packets()
            self._pending_anim.clear()
            self._animating = False
            self._last_tx_len = 0
            self.progress_var.set("Listo")

    # ---------- click en paquete (en pausa) ----------
    def _on_packet_clicked(self, meta: dict | None):
        if (not self._paused) and self._is_running:
            return
        if not meta:
            return
        self.sel_t.set(f"{meta.get('t',0):.2f}")
        self.sel_kind.set(str(meta.get("kind","—")))
        self.sel_seq.set(str(meta.get("seq","—")))
        self.sel_ack.set(str(meta.get("ack","—")))
        self.sel_info.set(str(meta.get("info","—")))


def main():
    root = tk.Tk()
    root.title("Simulador de Protocolos (Main)")
    root.geometry("1360x900")
    root.minsize(1220, 800)
    app = MainGUI(root)
    app.pack(fill="both", expand=True)
    root.mainloop()

if __name__ == "__main__":
    main()