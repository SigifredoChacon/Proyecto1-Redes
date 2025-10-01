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
    ANIM_DURATION_MS = 1400
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

        # límites y contadores
        self._steps_done = 0
        self._min_limit_by_proto = {
            "Utopia": 10,
            "Stop-and-Wait": 10,
            "PAR": 10,
            "Sliding Window 1-bit": 100,
            "Go-Back-N": 100,
            "Selective Repeat": 100,
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

    # ---------- estilos ----------
    def _setup_styles(self):
        style = ttk.Style()
        try: style.theme_use("clam")
        except: pass
        bg = "#0f172a"; fg = "#e2e8f0"; field = "#1e293b"
        style.configure(".", background=bg, foreground=fg)
        style.configure("Card.TLabelframe", background=bg, foreground=fg)
        style.configure("Card.TLabelframe.Label", foreground=fg)
        style.configure("TButton", padding=6)
        style.configure("TEntry", fieldbackground=field, foreground=fg)
        style.configure("TCombobox", fieldbackground=field, foreground=fg)
        style.configure("TSpinbox", fieldbackground=field, foreground=fg)
        style.configure("Treeview", fieldbackground=field, background=field, foreground=fg)
        style.configure("Treeview.Heading", background=bg, foreground=fg)
        style.map("TButton", background=[("active", "#334155")])

        root = self.master
        root.option_add("*TCombobox*Listbox*background", field)
        root.option_add("*TCombobox*Listbox*foreground", fg)
        root.option_add("*Listbox*background", field)
        root.option_add("*Listbox*foreground", fg)
        root.option_add("*Entry*foreground", fg)

    # ---------- layout ----------
    def _build_layout(self):
        left = ttk.Frame(self); left.pack(side="left", fill="y", padx=12, pady=12)
        right = ttk.Frame(self); right.pack(side="right", fill="both", expand=True, padx=12, pady=12)

        ttk.Label(left, text="Protocolo").pack(anchor="w")
        self.sel_proto = ttk.Combobox(
            left, state="readonly",
            values=["Utopia", "Stop-and-Wait", "PAR", "Sliding Window 1-bit", "Go-Back-N", "Selective Repeat"]
        )
        self.sel_proto.current(0)
        self.sel_proto.pack(fill="x", pady=(0,8))
        self.sel_proto.bind("<<ComboboxSelected>>", self._on_proto_change)

        self.delay = tk.DoubleVar(value=0.02)
        self.jitter = tk.DoubleVar(value=0.01)
        self.loss = tk.DoubleVar(value=0.0)
        self.corrupt = tk.DoubleVar(value=0.0)
        self.data_to = tk.DoubleVar(value=0.25)
        self.ack_to  = tk.DoubleVar(value=0.08)
        self.maxseq  = tk.IntVar(value=7)

        params = [
            ("Delay (s)", self.delay, 0.0, 5.0, 0.01),
            ("Jitter (s)", self.jitter, 0.0, 5.0, 0.01),
            ("Pérdida (0-1)", self.loss, 0.0, 1.0, 0.01),
            ("Corrupción (0-1)", self.corrupt, 0.0, 1.0, 0.01),
            ("DATA timeout (s)", self.data_to, 0.01, 5.0, 0.01),
            ("ACK timeout (s)", self.ack_to, 0.01, 5.0, 0.01),
            ("max_seq (2^n - 1)", self.maxseq, 1, 31, 2),
        ]
        for lbl, var, frm, to, inc in params:
            row = ttk.Frame(left); row.pack(fill="x", pady=3)
            ttk.Label(row, text=lbl).pack(side="left")
            ttk.Spinbox(row, textvariable=var, from_=frm, to=to, increment=inc, width=10).pack(side="right")

        # Límite de pasos
        limit_row = ttk.Frame(left); limit_row.pack(fill="x", pady=(12,6))
        ttk.Label(limit_row, text="Máximo de pasos").pack(side="left")
        self.step_limit_var = tk.IntVar(value=10)
        self.step_limit = ttk.Spinbox(
            limit_row, textvariable=self.step_limit_var, from_=10, to=1000000, increment=10, width=10
        )
        self.step_limit.pack(side="right")

        ttk.Button(left, text="Inicializar / Reset", command=self._reset).pack(fill="x", pady=(12,6))
        self.btn_auto = ttk.Button(left, text="Run (Generar→Animar)", command=self._auto_start)
        self.btn_auto.pack(fill="x", pady=(0,6))
        self.btn_pause = ttk.Button(left, text="⏯ Pausa", command=self._toggle_pause)
        self.btn_pause.pack(fill="x", pady=(0,6))
        ttk.Button(left, text="⏹ Stop", command=self._auto_stop).pack(fill="x", pady=(0,6))

        # Host de controles de plugin
        self.plugin_host = ttk.Labelframe(left, text="Controles del Protocolo", style="Card.TLabelframe")
        self.plugin_host.pack(fill="x", pady=(12, 6))

        # Estado
        state = ttk.Labelframe(right, text="Estado", style="Card.TLabelframe"); state.pack(fill="x")
        sg = ttk.Frame(state); sg.pack(fill="x", padx=10, pady=6)
        self.time_var = tk.StringVar(value="0.00 s")
        self.tx_total_var = tk.StringVar(value="0 (DATA 0 | ACK 0)")
        self.rx_total_var = tk.StringVar(value="0")
        self.eff_var = tk.StringVar(value="0.00")
        self.gp_var = tk.StringVar(value="0.00 pkts/s")
        self._kv(sg, 0, "t (sim)", self.time_var); self._kv(sg, 0, "TX totales", self.tx_total_var, col=1)
        self._kv(sg, 1, "RX entregados", self.rx_total_var); self._kv(sg, 1, "Eficiencia", self.eff_var, col=1)
        self._kv(sg, 2, "Goodput", self.gp_var)

        # Canvas (computadoras: use_nests=False)
        canvas_card = ttk.Labelframe(right, text="Topología / Tramas", style="Card.TLabelframe")
        canvas_card.pack(fill="x", pady=(8,6))
        self.anim = AnimationCanvas(canvas_card, height=260, use_nests=False)
        self.anim.pack(fill="x", padx=10, pady=10)
        self.anim.bind_click(self._on_packet_clicked)
        self.anim.set_on_finished(self._on_anim_finished)

        # Detalle de paquete
        detail = ttk.Labelframe(right, text="Detalle del paquete (pausa + click)", style="Card.TLabelframe")
        detail.pack(fill="x", pady=(6, 2))
        dg = ttk.Frame(detail); dg.pack(fill="x", padx=10, pady=6)
        self.sel_t = tk.StringVar(value="-"); self.sel_kind = tk.StringVar(value="-")
        self.sel_seq = tk.StringVar(value="-"); self.sel_ack = tk.StringVar(value="-"); self.sel_info = tk.StringVar(value="-")
        self._kv(dg, 0, "t", self.sel_t); self._kv(dg, 0, "kind", self.sel_kind, col=1)
        self._kv(dg, 1, "seq", self.sel_seq); self._kv(dg, 1, "ack", self.sel_ack, col=1)
        self._kv(dg, 2, "info", self.sel_info, col=0)

        # Tablas
        tables = ttk.Panedwindow(right, orient=tk.HORIZONTAL); tables.pack(fill="both", expand=True, pady=(8,0))
        self.tx_frame = ttk.Labelframe(tables, text="Frames Transmitidos", style="Card.TLabelframe")
        self.rx_frame = ttk.Labelframe(tables, text="Entregas (to_network_layer)", style="Card.TLabelframe")
        tables.add(self.tx_frame, weight=3); tables.add(self.rx_frame, weight=2)
        self.tx_tree = self._build_tx_table(self.tx_frame)
        self.rx_tree = self._build_rx_table(self.rx_frame)

        # Progreso
        status = ttk.Frame(right); status.pack(fill="x", pady=(6, 0))
        self.progress_var = tk.StringVar(value="Listo")
        ttk.Label(status, textvariable=self.progress_var, anchor="e").pack(side="right", padx=6)

        self.pack(fill="both", expand=True)
        self._apply_min_limit("Utopia")

    # ---------- helpers UI ----------
    def _kv(self, parent, r, k, var, col=0):
        frm = ttk.Frame(parent); frm.grid(row=r, column=col, sticky="ew", padx=6, pady=2)
        ttk.Label(frm, text=k + ": ").pack(side="left")
        ttk.Label(frm, textvariable=var, font=("", 10, "bold")).pack(side="left")

    def _build_tx_table(self, parent):
        cols = ("t", "kind", "seq", "ack", "info")
        tr = ttk.Treeview(parent, columns=cols, show="headings")
        for c, w in zip(cols, (80, 120, 60, 60, 520)):
            tr.heading(c, text=c); tr.column(c, width=w, anchor=tk.CENTER if c != "info" else tk.W)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=tr.yview)
        tr.configure(yscrollcommand=vsb.set)
        tr.pack(side="left", fill="both", expand=True, padx=(10,0), pady=10)
        vsb.pack(side="right", fill="y", padx=(0,10), pady=10)
        return tr

    def _build_rx_table(self, parent):
        cols = ("t", "data")
        tr = ttk.Treeview(parent, columns=cols, show="headings")
        for c, w in zip(cols, (80, 600)):
            tr.heading(c, text=c); tr.column(c, width=w, anchor=tk.CENTER if c == "t" else tk.W)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=tr.yview)
        tr.configure(yscrollcommand=vsb.set)
        tr.pack(side="left", fill="both", expand=True, padx=(10,0), pady=10)
        vsb.pack(side="right", fill="y", padx=(0,10), pady=10)
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

        # Reglas del enunciado: Utopía / Stop-and-Wait sin errores en canal
        if name in ("Utopia", "Stop-and-Wait"):
            self.loss.set(0.0); self.corrupt.set(0.0)

    def _cfg(self) -> SimConfig:
        return SimConfig(
            delay=float(self.delay.get()), jitter=float(self.jitter.get()),
            loss_prob=float(self.loss.get()), corrupt_prob=float(self.corrupt.get()),
            data_timeout=float(self.data_to.get()), ack_timeout=float(self.ack_to.get()),
            max_seq=int(self.maxseq.get()), nr_bufs=(int(self.maxseq.get()) + 1) // 2,
        )

    # ---------- acciones ----------
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
        self.btn_pause.configure(text="⏯ Pausa")

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
        self.btn_pause.configure(text="⏯ Pausa")
        self.btn_auto.configure(text="Generando…")
        self.anim.set_running(False)
        self._start_generation_phase()

    def _auto_stop(self):
        self._is_running = False
        self._paused = False
        self.anim.set_running(False)
        self.btn_auto.configure(text="Run (Generar→Animar)")
        self.btn_pause.configure(text="⏯ Pausa")
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
            self.btn_auto.configure(text="Animando…")
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
    root.geometry("1320x880")
    root.minsize(1200, 780)
    app = MainGUI(root)
    app.pack(fill="both", expand=True)
    root.mainloop()

if __name__ == "__main__":
    main()