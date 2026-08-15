# -*- coding: utf-8 -*-
"""
JARVIS — premium futuristic AI workstation interface.

A from-scratch visual rewrite built on PyQt6. Architecture is component-based:

    ModernPanel     — glassmorphism surface
    SystemMetric    — compact metric with a live sparkline
    JarvisCore      — central AI-core / neural-energy visualization
    ActivityPanel   — premium conversation panel (message bubbles)
    CommandBar      — bottom command bar (microphone, input, controls)
    MicrophoneButton— animated round microphone toggle

All original integration points are preserved (JarvisUI, MainWindow signals,
camera stream, file drop, clipboard, setup/customize/remote overlays, psutil
metrics, face.png support, keyboard shortcuts).
"""

from __future__ import annotations

import json
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

if platform.system() == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}

from PyQt6.QtCore import (
    QAbstractNativeEventFilter, QPointF, QRectF, Qt, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QConicalGradient, QDragEnterEvent, QDropEvent, QFont,
    QIcon, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QSizePolicy, QSlider, QSplitter,
    QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR   = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"


def _read_full_config() -> dict:
    try:
        return json.loads(API_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


_DEFAULT_W, _DEFAULT_H = 1280, 720
_MIN_W,     _MIN_H     = 960, 600
_LEFT_W  = 200
_RIGHT_W = 330

_OS = platform.system()

# ── typography ─────────────────────────────────────────────────────────────────
_UI_FONT   = "Segoe UI"
_MONO_FONT = "Consolas"


# ── palette ────────────────────────────────────────────────────────────────────
class C:
    BG        = "#0a0d10"
    PANEL     = "#10151a"
    PANEL2    = "#141b21"
    BORDER    = "#1f2b34"
    BORDER_B  = "#2c3f4d"
    BORDER_A  = "#25333e"
    PRI       = "#3ec8ff"
    PRI_DIM   = "#1f6f93"
    PRI_GHO   = "#0e2632"
    ACC       = "#ff7a3d"
    ACC2      = "#ffc44d"
    GREEN     = "#3ddc97"
    GREEN_D   = "#1f9d6b"
    RED       = "#ff5c6c"
    MUTED_C   = "#ff5c6c"
    TEXT      = "#d5ecf7"
    TEXT_DIM  = "#5e7f8e"
    TEXT_MED  = "#93b7c6"
    WHITE     = "#eef7ff"
    DARK      = "#07090b"
    BAR_BG    = "#141b21"


_HUE_LINKED = (
    "BG", "PANEL", "PANEL2", "BORDER", "BORDER_B", "BORDER_A",
    "PRI", "PRI_DIM", "PRI_GHO", "TEXT", "TEXT_DIM", "TEXT_MED",
    "WHITE", "DARK", "BAR_BG",
)
_PALETTE_DEFAULTS: dict[str, str] = {k: getattr(C, k) for k in _HUE_LINKED}
DEFAULT_UI_COLOR = _PALETTE_DEFAULTS["PRI"]


def apply_ui_accent(accent_hex: str) -> bool:
    import colorsys

    accent_hex = (accent_hex or "").strip().lower()
    if not (accent_hex.startswith("#") and len(accent_hex) == 7):
        return False
    try:
        int(accent_hex[1:], 16)
    except ValueError:
        return False

    def _hsv(h: str) -> tuple[float, float, float]:
        r = int(h[1:3], 16) / 255
        g = int(h[3:5], 16) / 255
        b = int(h[5:7], 16) / 255
        return colorsys.rgb_to_hsv(r, g, b)

    base_h = _hsv(_PALETTE_DEFAULTS["PRI"])[0]
    acc_h, acc_s, _av = _hsv(accent_hex)
    dh   = acc_h - base_h
    grey = acc_s < 0.08

    for key, hex0 in _PALETTE_DEFAULTS.items():
        h, s, v = _hsv(hex0)
        if grey:
            s *= 0.15
        r, g, b = colorsys.hsv_to_rgb((h + dh) % 1.0, s, v)
        setattr(C, key, "#{:02x}{:02x}{:02x}".format(
            int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5)))
    return True


def current_palette() -> dict[str, str]:
    return {k: getattr(C, k) for k in _HUE_LINKED}


def retheme_all_widgets(old: dict[str, str], new: dict[str, str]) -> None:
    mapping = {old[k].lower(): new[k].lower()
               for k in old if old[k].lower() != new.get(k, old[k]).lower()}
    if not mapping:
        return
    app = QApplication.instance()
    if app is None:
        return
    for w in app.allWidgets():
        try:
            ss = w.styleSheet()
            if ss:
                s2 = ss
                for o, n in mapping.items():
                    if o in s2:
                        s2 = s2.replace(o, n)
                if s2 != ss:
                    w.setStyleSheet(s2)
            w.update()
        except Exception:
            pass


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h)
    c.setAlpha(a)
    return c


# ── system metrics (psutil, zero subprocess) ──────────────────────────────────
_nvml_lib: object = None
_nvml_ok:  object = None


def _nvml_gpu_windows() -> float:
    global _nvml_lib, _nvml_ok
    if _nvml_ok is False:
        return -1.0
    try:
        import ctypes

        class _Util(ctypes.Structure):
            _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

        if _nvml_lib is None:
            for dll_name in ("nvml", r"C:\Windows\System32\nvml.dll"):
                try:
                    lib = ctypes.WinDLL(dll_name)
                    lib.nvmlInit_v2()
                    _nvml_lib = lib
                    break
                except Exception:
                    continue

        if _nvml_lib is None:
            import pynvml
            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            _nvml_ok = True
            return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)

        dev = ctypes.c_void_p()
        _nvml_lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
        util = _Util()
        _nvml_lib.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(util))
        _nvml_ok = True
        return float(util.gpu)
    except Exception:
        _nvml_ok = False
        return -1.0


class _SysMetrics:
    def __init__(self):
        self.cpu = 0.0
        self.mem = 0.0
        self.net = 0.0
        self.gpu = -1.0
        self.tmp = -1.0
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        while self._running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(1.5)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        nc  = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._last_net_t
        if dt > 0:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net  = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net   = nc
        self._last_net_t = now

        gpu = self._get_gpu()
        tmp = self._get_temp()

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = gpu
            self.tmp = tmp

    def _get_gpu(self) -> float:
        try:
            import pynvml
            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
        except Exception:
            pass
        if _OS == "Windows":
            return _nvml_gpu_windows()
        try:
            import ctypes
            _lib = "libnvidia-ml.so.1" if _OS == "Linux" else "libnvidia-ml.dylib"

            class _Util(ctypes.Structure):
                _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

            nv = ctypes.CDLL(_lib)
            nv.nvmlInit_v2()
            dev = ctypes.c_void_p()
            nv.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
            u = _Util()
            nv.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(u))
            return float(u.gpu)
        except Exception:
            pass
        return -1.0

    def _get_temp(self) -> float:
        try:
            temps = psutil.sensors_temperatures()
            for name in ["coretemp", "k10temp", "cpu_thermal", "acpitz",
                         "cpu-thermal", "zenpower", "it8688"]:
                if name in temps and temps[name]:
                    return temps[name][0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass
        if _OS == "Windows":
            try:
                import wmi
                w = wmi.WMI(namespace="root/wmi")
                tz = w.MSAcpi_ThermalZoneTemperature()
                if tz:
                    return (tz[0].CurrentTemperature / 10.0) - 273.15
            except Exception:
                pass
        return -1.0

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
            }


_metrics = _SysMetrics()


# ══════════════════════════════════════════════════════════════════════════════
#  Reusable components
# ══════════════════════════════════════════════════════════════════════════════

class ModernPanel(QFrame):
    """Glassmorphism surface: rounded, translucent, soft border + top highlight."""

    def __init__(self, title: str = "", parent=None, radius: int = 12):
        super().__init__(parent)
        self.setObjectName("ModernPanel")
        self._radius = radius
        self._title  = title
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(14, 14, 14, 14)
        self._lay.setSpacing(10)

        if title:
            lbl = QLabel(title.upper())
            lbl.setFont(QFont(_UI_FONT, 8, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; "
                              f"letter-spacing: 1px;")
            self._lay.addWidget(lbl)
            self._title_rule = True
        else:
            self._title_rule = False

    def layout(self):
        return self._lay

    def addWidget(self, w, *a, **k):
        self._lay.addWidget(w, *a, **k)

    def addLayout(self, l, *a, **k):
        self._lay.addLayout(l, *a, **k)

    def addStretch(self, n=0):
        self._lay.addStretch(n)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = self._radius

        # glass body — vertical gradient, translucent graphite
        grad = QLinearGradient(0, r.top(), 0, r.bottom())
        grad.setColorAt(0.0, qcol("#151b21", 235))
        grad.setColorAt(1.0, qcol("#0c1116", 235))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(r, rad, rad)

        # soft border
        p.setPen(QPen(qcol(C.BORDER_B, 150), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, rad, rad)

        # top highlight (glass sheen)
        sheen = QLinearGradient(0, r.top(), 0, r.top() + 26)
        sheen.setColorAt(0.0, qcol(C.WHITE, 18))
        sheen.setColorAt(1.0, qcol(C.WHITE, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(sheen))
        p.drawRoundedRect(r.adjusted(1, 1, -1, -1), rad - 1, rad - 1)

        if self._title_rule:
            y = self._lay.contentsMargins().top() + 20
            p.setPen(QPen(qcol(C.BORDER, 120), 1))
            p.drawLine(QPointF(r.left() + 14, y), QPointF(r.right() - 14, y))


class SystemMetric(QWidget):
    """Compact metric: label, value and a live sparkline graph."""

    def __init__(self, label: str, color: str = C.PRI, parent=None,
                 unit: str = "%"):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._unit  = unit
        self._value = 0.0
        self._text  = "--"
        self._hist: list[float] = [0.0] * 40
        self.setFixedHeight(50)
        self.setMinimumWidth(120)

    def set_value(self, pct: float, text: str):
        self._value = max(0.0, min(100.0, pct))
        self._text  = text
        self._hist.append(self._value)
        self._hist = self._hist[-40:]
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        # label
        p.setFont(QFont(_MONO_FONT, 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM, 200), 1))
        p.drawText(QRectF(0, 0, 40, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._label)

        # value
        if self._value > 85:
            vcol = C.RED
        elif self._value > 65:
            vcol = C.ACC
        else:
            vcol = self._color
        p.setFont(QFont(_MONO_FONT, 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(vcol if self._text != "--" else C.TEXT_DIM, 230), 1))
        p.drawText(QRectF(W - 70, 0, 70, 16),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   self._text)

        # sparkline
        gx, gy = 0, 20
        gw, gh = W, H - 22
        n = len(self._hist)
        if n >= 2:
            path = QPainterPath()
            for i, v in enumerate(self._hist):
                x = gx + (i / (n - 1)) * gw
                y = gy + gh - (v / 100.0) * gh
                if i == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            p.setPen(QPen(qcol(self._color, 150), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

            # area fill
            area = QPainterPath(path)
            area.lineTo(gx + gw, gy + gh)
            area.lineTo(gx, gy + gh)
            area.closeSubpath()
            fill = QLinearGradient(0, gy, 0, gy + gh)
            fill.setColorAt(0.0, qcol(self._color, 60))
            fill.setColorAt(1.0, qcol(self._color, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(fill))
            p.drawPath(area)


class JarvisCore(QWidget):
    """
    Central AI-core / neural-energy visualization.

    A breathing energy sphere surrounded by a slowly rotating neural
    constellation, a horizontal waveform ribbon and drifting particles.
    Reacts to LISTENING / THINKING / PROCESSING / SPEAKING / MUTED / STANDBY.
    """

    def __init__(self, face_path: str = "", assistant_name: str = "JARVIS",
                 parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(320, 320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted    = False
        self.speaking = False
        self.state    = "INITIALISING"
        self._assistant_name = assistant_name

        self._t          = 0.0
        self._last_t     = time.time()
        self._breathe    = 0.0
        self._glow       = 30.0
        self._pulse      = 0.0
        self._burst      = 0.0
        self._prev_speak = False
        self._wave       = [0.0] * 96
        self._particles: list[list[float]] = []
        self._nodes      = [random.uniform(0, 2 * math.pi) for _ in range(7)]
        self._node_speed = [random.uniform(0.05, 0.14) for _ in range(7)]
        self._node_r     = [random.uniform(0.80, 1.10) for _ in range(7)]
        self._face_px: QPixmap | None = None

        if face_path:
            self._load_face(face_path)

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(16)

    def _load_face(self, path: str):
        try:
            from PIL import Image, ImageDraw
            import io
            img = Image.open(path).convert("RGBA")
            sz  = min(img.size)
            img = img.resize((sz, sz), Image.LANCZOS)
            mk  = Image.new("L", (sz, sz), 0)
            ImageDraw.Draw(mk).ellipse((2, 2, sz - 2, sz - 2), fill=255)
            img.putalpha(mk)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap()
            px.loadFromData(buf.getvalue())
            self._face_px = px
        except Exception:
            self._face_px = None

    def _accent(self) -> str:
        if self.muted:
            return C.MUTED_C
        if self.speaking:
            return C.PRI
        if self.state in ("THINKING", "PROCESSING"):
            return C.ACC2
        return C.PRI

    def _activity(self) -> float:
        if self.speaking:
            return 1.0
        if self.state in ("THINKING", "PROCESSING"):
            return 0.55
        if self.state == "LISTENING":
            return 0.40
        if self.muted:
            return 0.03
        return 0.12

    def _status_label(self) -> tuple[str, str]:
        if self.muted:
            return "MUTED", C.MUTED_C
        if self.speaking:
            return "SPEAKING", C.PRI
        if self.state == "THINKING":
            return "ANALYZING", C.ACC2
        if self.state == "PROCESSING":
            return "PROCESSING", C.ACC2
        if self.state == "LISTENING":
            return "LISTENING", C.PRI
        if self.state == "SLEEPING":
            return "STANDBY", C.TEXT_DIM
        if self.state == "INITIALISING":
            return "INITIALISING", C.PRI_DIM
        return "STANDBY", C.PRI_DIM

    def _step(self):
        now = time.time()
        dt  = max(0.0, min(0.05, now - self._last_t))
        self._last_t = now
        self._t      += dt
        act = self._activity()

        if self.speaking and not self._prev_speak:
            self._burst = 1.0
        self._prev_speak = self.speaking
        self._burst = max(0.0, self._burst - dt * 2.2)

        self._breathe += dt

        # glow target by state
        if self.speaking:
            tgt = 92.0 + 22.0 * math.sin(self._t * 8.0)
        elif self.state in ("THINKING", "PROCESSING"):
            tgt = 66.0 + 10.0 * math.sin(self._t * 4.0)
        elif self.state == "LISTENING":
            tgt = 52.0 + 6.0 * math.sin(self._t * 2.0)
        elif self.muted:
            tgt = 8.0
        else:
            tgt = 26.0 + 5.0 * math.sin(self._t * 1.4)
        self._glow += (tgt - self._glow) * (1.0 - math.exp(-dt * 5.0))

        self._pulse += dt * (0.30 if self.speaking else 0.08)
        if self._pulse > 1.0:
            self._pulse = 0.0

        # waveform
        if self.speaking:
            amp = 0.9 + 0.5 * self._burst
        elif self.state == "LISTENING":
            amp = 0.35
        elif self.state in ("THINKING", "PROCESSING"):
            amp = 0.22
        else:
            amp = 0.06
        if self.muted:
            amp = 0.0
        for i in range(len(self._wave)):
            ph = self._t * (3.4 + 2.6 * act) + i * 0.34
            self._wave[i] = (math.sin(ph) * 0.55 + math.sin(ph * 2.31 + i) * 0.30
                             + math.sin(ph * 4.7) * 0.15) * amp

        # nodes drift
        for i in range(len(self._nodes)):
            self._nodes[i] += dt * self._node_speed[i] * (0.5 + act)

        # particles
        cx, cy = self.width() / 2, self.height() / 2
        fw = min(self.width(), self.height())
        if random.random() < (0.02 + 0.09 * act):
            ang = random.uniform(0, 2 * math.pi)
            r   = fw * random.uniform(0.15, 0.55)
            self._particles.append([
                cx + math.cos(ang) * r,
                cy + math.sin(ang) * r,
                random.uniform(-0.5, 0.5),
                random.uniform(-1.4, -0.4),
                random.uniform(0.4, 1.0),
                random.uniform(0.8, 2.0),
            ])
        kept: list[list[float]] = []
        for pt in self._particles:
            x, y, vx, vy, life, sz = pt
            x += vx * dt * 18.0
            y += vy * dt * 18.0
            life -= dt * 0.30
            if life > 0:
                kept.append([x, y, vx, vy, life, sz])
        self._particles = kept

        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)
        act   = self._activity()
        glow  = self._glow
        acc   = self._accent()

        # 1) background — graphite with a faint cyan core glow
        bg = QLinearGradient(0, 0, 0, H)
        bg.setColorAt(0.0, QColor("#0c1014"))
        bg.setColorAt(1.0, QColor("#07090b"))
        p.fillRect(self.rect(), QBrush(bg))

        halo = QRadialGradient(cx, cy, fw * 0.62)
        halo.setColorAt(0.0, qcol(acc, int(18 + 26 * act)))
        halo.setColorAt(1.0, qcol(acc, 0))
        p.fillRect(self.rect(), QBrush(halo))

        # 2) face — faint, behind the core (the startup photo is shown as a
        # separate splash before this window appears)
        if self._face_px:
            fsz = int(fw * 0.30)
            scaled = self._face_px.scaled(
                fsz, fsz,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.setOpacity(0.10)
            p.drawPixmap(int(cx - fsz / 2), int(cy - fsz / 2), scaled)
            p.setOpacity(1.0)

        core_r = fw * (0.15 + 0.012 * math.sin(self._breathe * 1.4))

        # 3) neural constellation — faint lines + drifting nodes
        node_pts = []
        for i, a0 in enumerate(self._nodes):
            a = a0
            r = core_r * self._node_r[i] * 2.6
            nx = cx + math.cos(a) * r
            ny = cy + math.sin(a) * r * 0.72
            node_pts.append((nx, ny))

        p.setPen(QPen(qcol(acc, int(16 + 30 * act)), 1))
        for i, (nx, ny) in enumerate(node_pts):
            # center link
            p.drawLine(QPointF(cx, cy), QPointF(nx, ny))
            # neighbor link
            nx2, ny2 = node_pts[(i + 1) % len(node_pts)]
            p.drawLine(QPointF(nx, ny), QPointF(nx2, ny2))

        for i, (nx, ny) in enumerate(node_pts):
            pulse = 0.5 + 0.5 * math.sin(self._t * 2.0 + i * 1.1)
            sz = 1.6 + 1.6 * pulse * act
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(acc, int(120 + 100 * pulse * act))))
            p.drawEllipse(QPointF(nx, ny), sz, sz)

        # 4) core sphere — layered, with an off-centre light source (3D depth)
        for i in range(6):
            frc = 1.0 - i / 6
            r = core_r * (2.6 - i * 0.26)
            a = int(glow * 0.85 * frc)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(acc, max(0, min(255, a)))))
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        sphere = QRadialGradient(cx - core_r * 0.35, cy - core_r * 0.42, core_r * 1.7)
        sphere.setColorAt(0.0, qcol(C.WHITE, 235))
        sphere.setColorAt(0.25, qcol(acc, 210))
        sphere.setColorAt(0.65, qcol(acc, 70))
        sphere.setColorAt(1.0, qcol(C.DARK, 40))
        p.setPen(QPen(qcol(C.WHITE, int(40 + glow * 1.2)), 1))
        p.setBrush(QBrush(sphere))
        p.drawEllipse(QRectF(cx - core_r, cy - core_r, core_r * 2, core_r * 2))

        # 5) waveform ribbon — horizontal energy line across the core
        if amp := max(abs(x) for x in self._wave):
            n = len(self._wave)
            span = core_r * 2.9
            mid_y = cy + core_r * 0.05
            path = QPainterPath()
            for i in range(n + 1):
                idx = i % n
                x = cx - span + (i / n) * 2 * span
                y = mid_y + self._wave[idx] * core_r * 0.55
                if i == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            p.setPen(QPen(qcol(acc, min(255, int(90 + glow))), 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

        # 6) breathing pulse ring (subtle, single)
        if act > 0.05 and not self.muted:
            pr = core_r * (1.3 + self._pulse * 1.1)
            al = int(70 * (1.0 - self._pulse))
            p.setPen(QPen(qcol(acc, al), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - pr, cy - pr, pr * 2, pr * 2))

        # 7) particles
        for pt in self._particles:
            x, y, _vx, _vy, life, sz = pt
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(acc, int(160 * life))))
            p.drawEllipse(QPointF(x, y), sz, sz)

        # 8) status label
        txt, col = self._status_label()
        sy = cy + fw * 0.46
        p.setFont(QFont(_UI_FONT, 10, QFont.Weight.Light))
        p.setPen(QPen(qcol(col, 210), 1))
        p.drawText(QRectF(0, sy, W, 22), Qt.AlignmentFlag.AlignCenter, txt)

        # 9) corner brackets — minimal
        bl, m = 14, 10
        p.setPen(QPen(qcol(C.BORDER_B, 90), 1))
        for bx, by, dx, dy in ((m, m, 1, 1), (W - m, m, -1, 1),
                               (m, H - m, 1, -1), (W - m, H - m, -1, -1)):
            p.drawLine(QPointF(bx, by), QPointF(bx + dx * bl, by))
            p.drawLine(QPointF(bx, by), QPointF(bx, by + dy * bl))


class _MessageBubble(QFrame):
    """A single conversation bubble inside the ActivityPanel."""

    def __init__(self, text: str, kind: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Bubble")

        styles = {
            "you":  (qcol(C.PRI, 26),   C.TEXT, C.PRI),
            "ai":   (qcol(C.PANEL2, 240), C.TEXT, C.BORDER_B),
            "err":  (qcol(C.RED, 22),   "#ffb3bd", C.RED),
            "file": (qcol(C.GREEN, 20), "#bff2dd", C.GREEN_D),
        }
        bg, fg, edge = styles.get(kind, (qcol(C.PANEL2, 200), C.TEXT_DIM, C.BORDER))

        self.setStyleSheet(f"""
            QFrame#Bubble {{
                background: rgba({bg.red()}, {bg.green()}, {bg.blue()}, {bg.alpha()});
                border: 1px solid {edge};
                border-radius: 10px;
            }}
        """)

        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setFont(QFont(_UI_FONT, 9))
        lbl.setStyleSheet(f"color: {fg}; background: transparent; padding: 2px;")
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.addWidget(lbl)


class ActivityPanel(QWidget):
    """Premium conversation panel — message bubbles instead of a terminal log."""

    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ai_name_lc = "jarvis"

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: transparent; width: 6px; margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B}; border-radius: 3px; min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        """)

        self._content = QWidget()
        self._content.setStyleSheet("background: transparent;")
        self._list = QVBoxLayout(self._content)
        self._list.setContentsMargins(4, 4, 4, 4)
        self._list.setSpacing(7)
        self._list.addStretch(1)
        self._scroll.setWidget(self._content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._scroll)

        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        tl = text.lower()
        ai_pfx = f"{self._ai_name_lc}:"
        if tl.startswith("you:"):
            kind = "you"
        elif tl.startswith(ai_pfx) or tl.startswith("jarvis:"):
            kind = "ai"
        elif tl.startswith("file:"):
            kind = "file"
        elif "err" in tl or tl.startswith("error"):
            kind = "err"
        else:
            kind = "sys"

        bubble = _MessageBubble(text, kind)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if kind == "you":
            row.addStretch(1)
            row.addWidget(bubble, 3)
        elif kind == "sys":
            row.addStretch(1)
            row.addWidget(bubble, 4)
            row.addStretch(1)
        else:
            row.addWidget(bubble, 3)
            row.addStretch(1)

        self._list.insertLayout(self._list.count() - 1, row)
        QTimer.singleShot(0, self._scroll_bottom)

    def _scroll_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())


class MicrophoneButton(QPushButton):
    """Round microphone toggle — glows when live, dims/reddens when muted."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._muted = False
        self._pulse = 0.0
        self.setFixedSize(44, 44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Toggle microphone")
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._tick)
        self._tmr.start(40)

    def set_muted(self, muted: bool):
        self._muted = muted
        self.update()

    def _tick(self):
        self._pulse = (self._pulse + 0.05) % (2 * math.pi)
        if not self._muted:
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2

        if self._muted:
            ring = C.MUTED_C
            fill = "#2a0d11"
            icon = C.MUTED_C
        else:
            ring = C.PRI
            fill = "#0e2632"
            icon = C.PRI

        # soft pulse halo when live
        if not self._muted:
            halo = 14 + 4 * (0.5 + 0.5 * math.sin(self._pulse))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(ring, 40)))
            p.drawEllipse(QRectF(cx - halo, cy - halo, halo * 2, halo * 2))

        # button disc
        p.setPen(QPen(qcol(ring, 220), 1.4))
        p.setBrush(QBrush(QColor(fill)))
        p.drawEllipse(QRectF(cx - 16, cy - 16, 32, 32))

        # mic glyph
        p.setPen(QPen(qcol(icon, 240), 1.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        # capsule
        p.drawRoundedRect(QRectF(cx - 4, cy - 10, 8, 13), 3, 3)
        # arc
        p.drawArc(QRectF(cx - 9, cy - 5, 18, 18), 20 * 16, 140 * 16)
        # stem
        p.drawLine(QPointF(cx, cy + 3), QPointF(cx, cy + 7))
        # base
        p.drawLine(QPointF(cx - 5, cy + 7), QPointF(cx + 5, cy + 7))


class CommandBar(QWidget):
    """Bottom command bar: microphone, text input and quick controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CommandBar")
        self.setFixedHeight(58)
        self.setStyleSheet(
            f"QWidget#CommandBar {{ background: {C.DARK}; "
            f"border-top: 1px solid {C.BORDER_B}; }}"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(10)

        self.mic_btn = MicrophoneButton()
        lay.addWidget(self.mic_btn)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Speak, or type a command…")
        self.input.setFont(QFont(_UI_FONT, 10))
        self.input.setFixedHeight(40)
        self.input.setStyleSheet(f"""
            QLineEdit {{
                background: {C.PANEL}; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 20px; padding: 0 16px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        lay.addWidget(self.input, stretch=1)

        send = QPushButton("▸")
        send.setFixedSize(40, 40)
        send.setFont(QFont(_UI_FONT, 14, QFont.Weight.Bold))
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PRI_GHO}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 20px;
            }}
            QPushButton:hover {{ background: {C.PRI_DIM}; color: {C.DARK}; }}
        """)
        lay.addWidget(send)

        self.interrupt_btn = QPushButton("✋  INTERRUPT")
        self.interrupt_btn.setFixedHeight(40)
        self.interrupt_btn.setFont(QFont(_UI_FONT, 8, QFont.Weight.Bold))
        self.interrupt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.interrupt_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 20px; padding: 0 14px;
            }}
            QPushButton:hover {{ color: {C.RED}; border-color: {C.RED}; }}
        """)
        lay.addWidget(self.interrupt_btn)

        vol_lbl = QLabel("VOL")
        vol_lbl.setFont(QFont(_MONO_FONT, 7, QFont.Weight.Bold))
        vol_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        lay.addWidget(vol_lbl)

        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(100)
        self.volume.setFixedWidth(90)
        self.volume.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 4px; background: {C.BAR_BG};
                border: 1px solid {C.BORDER}; border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{ background: {C.PRI_DIM}; border-radius: 2px; }}
            QSlider::handle:horizontal {{
                width: 14px; margin: -5px 0;
                background: {C.PRI}; border-radius: 7px; border: 1px solid {C.BORDER_B};
            }}
        """)
        lay.addWidget(self.volume)


# ══════════════════════════════════════════════════════════════════════════════
#  File handling / overlays (preserved interfaces, restyled)
# ══════════════════════════════════════════════════════════════════════════════

_FILE_ICONS = {
    "image":   ("🖼", "#3ec8ff"), "video":   ("🎬", "#ff7a3d"),
    "audio":   ("🎵", "#b98cff"), "pdf":     ("📄", "#ff5c6c"),
    "word":    ("📝", "#5c8cff"), "excel":   ("📊", "#3ddc97"),
    "code":    ("💻", "#ffc44d"), "archive": ("📦", "#ff8a4d"),
    "pptx":    ("📊", "#ff8a5c"), "text":    ("📃", "#9fb2bd"),
    "data":    ("🔧", "#8fd4f2"), "unknown": ("📎", "#7a8a94"),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg","jpeg","png","gif","webp","bmp","tiff","svg","ico"], "image"),
    **dict.fromkeys(["mp4","avi","mov","mkv","wmv","flv","webm","m4v"],         "video"),
    **dict.fromkeys(["mp3","wav","ogg","m4a","aac","flac","wma","opus"],        "audio"),
    **dict.fromkeys(["pdf"],                                                     "pdf"),
    **dict.fromkeys(["doc","docx"],                                              "word"),
    **dict.fromkeys(["xls","xlsx","ods"],                                        "excel"),
    **dict.fromkeys(["ppt","pptx"],                                              "pptx"),
    **dict.fromkeys(["py","js","ts","jsx","tsx","html","css","java","c","cpp",
                     "cs","go","rs","rb","php","swift","kt","sh","sql","lua"],   "code"),
    **dict.fromkeys(["zip","rar","tar","gz","7z","bz2","xz"],                   "archive"),
    **dict.fromkeys(["txt","md","rst","log"],                                    "text"),
    **dict.fromkeys(["csv","tsv","json","xml"],                                  "data"),
}


def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")


def _fmt_size(size: int) -> str:
    if   size < 1024:    return f"{size} B"
    elif size < 1024**2: return f"{size/1024:.1f} KB"
    elif size < 1024**3: return f"{size/1024**2:.1f} MB"
    else:                return f"{size/1024**3:.1f} GB"


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(74)
        self._current_file: str | None = None
        self._hovering  = False
        self._drag_over = False
        self._dash_offset = 0.0
        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        self._anim_tmr.start(40)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._canvas = _DropCanvas(self)
        layout.addWidget(self._canvas)

    def _animate(self):
        self._dash_offset = (self._dash_offset + 0.8) % 20
        self._canvas.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True
            self._canvas.update()

    def dragLeaveEvent(self, e):
        self._drag_over = False
        self._canvas.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self._canvas.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._browse()

    def enterEvent(self, e):
        self._hovering = True
        self._canvas.update()

    def leaveEvent(self, e):
        self._hovering = False
        self._canvas.update()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None
        self._canvas.update()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a file for JARVIS", str(Path.home()),
            "All Files (*.*);;"
            "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;"
            "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
            "Data (*.csv *.xlsx *.json *.xml);;"
            "Code (*.py *.js *.ts *.html *.css *.java *.cpp *.go);;"
            "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;"
            "Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm);;"
            "Archives (*.zip *.rar *.tar *.gz *.7z)",
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self._canvas.update()
        self.file_selected.emit(path)


class _DropCanvas(QWidget):
    def __init__(self, zone: FileDropZone):
        super().__init__(zone)
        self._z = zone

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        z    = self._z
        W, H = self.width(), self.height()
        pad  = 5
        rect = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        bg_col = qcol("#152028" if z._drag_over else ("#101820" if z._hovering else C.PANEL))
        p.setBrush(QBrush(bg_col))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 8, 8)

        if z._current_file:   border_col = qcol(C.GREEN, 190)
        elif z._drag_over:    border_col = qcol(C.PRI, 220)
        elif z._hovering:     border_col = qcol(C.BORDER_B, 200)
        else:                 border_col = qcol(C.BORDER, 160)
        pen = QPen(border_col, 1.4, Qt.PenStyle.DashLine)
        pen.setDashOffset(z._dash_offset)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 8, 8)

        if z._current_file:
            self._paint_file(p, W, H)
        elif z._drag_over:
            self._paint_drag_over(p, W, H)
        else:
            self._paint_idle(p, W, H, z._hovering)

    def _paint_idle(self, p, W, H, hover):
        cx, cy = W / 2, H / 2
        col = qcol(C.PRI_DIM if not hover else C.PRI)
        p.setPen(QPen(col, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx, cy - 11), QPointF(cx, cy + 4))
        p.drawLine(QPointF(cx - 7, cy - 4), QPointF(cx, cy - 11))
        p.drawLine(QPointF(cx + 7, cy - 4), QPointF(cx, cy - 11))
        p.drawLine(QPointF(cx - 12, cy + 4), QPointF(cx + 12, cy + 4))
        p.setFont(QFont(_UI_FONT, 8))
        p.setPen(QPen(qcol(C.PRI_DIM if not hover else C.TEXT), 1))
        p.drawText(QRectF(0, cy + 8, W, 16), Qt.AlignmentFlag.AlignCenter,
                   "Drop a file  ·  or click to browse")

    def _paint_drag_over(self, p, W, H):
        cx, cy = W / 2, H / 2
        p.setFont(QFont(_UI_FONT, 16))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy - 20, W, 28), Qt.AlignmentFlag.AlignCenter, "⬇")
        p.setFont(QFont(_UI_FONT, 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy + 8, W, 16), Qt.AlignmentFlag.AlignCenter,
                   "Release to load")

    def _paint_file(self, p, W, H):
        path = Path(self._z._current_file)
        cat  = _file_category(path)
        icon, icon_col = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size_str = _fmt_size(path.stat().st_size)
        ext_str  = path.suffix.upper().lstrip(".") or "FILE"

        p.setFont(QFont("Segoe UI Emoji", 18) if _OS == "Windows" else QFont("Arial", 18))
        p.setPen(QPen(qcol(icon_col), 1))
        p.drawText(QRectF(10, 0, 44, H), Qt.AlignmentFlag.AlignCenter, icon)

        tx = 60
        tw = W - tx - 30
        p.setFont(QFont(_UI_FONT, 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.WHITE), 1))
        name = path.name if len(path.name) <= 30 else path.name[:27] + "…"
        p.drawText(QRectF(tx, H * 0.20, tw, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        p.setFont(QFont(_MONO_FONT, 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(tx, H * 0.20 + 16, tw, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{ext_str}  ·  {size_str}")

        p.setFont(QFont(_UI_FONT, 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.RED, 180), 1))
        p.drawText(QRectF(W - 26, 0, 20, H), Qt.AlignmentFlag.AlignCenter, "✕")

    def mousePressEvent(self, e):
        z = self._z
        if z._current_file and e.pos().x() > self.width() - 30:
            z.clear_file()
        else:
            z.mousePressEvent(e)


class _CameraPreview(QWidget):
    """Floating overlay that briefly shows what the camera captured."""

    _W, _H = 260, 200

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            _CameraPreview {{
                background: rgba(7, 10, 14, 246);
                border: 1px solid {C.BORDER_B};
                border-radius: 12px;
            }}
        """)
        self.setFixedWidth(self._W)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 7, 8, 8)
        lay.setSpacing(5)

        hdr = QHBoxLayout()
        title = QLabel("◈  VISUAL INPUT")
        title.setFont(QFont(_MONO_FONT, 7, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(title)
        hdr.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(18, 18)
        close_btn.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.hide)
        hdr.addWidget(close_btn)
        lay.addLayout(hdr)

        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet("background: transparent;")
        lay.addWidget(self._img_lbl)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def show_frame(self, img_bytes: bytes) -> None:
        px = QPixmap()
        px.loadFromData(img_bytes)
        if not px.isNull():
            max_w = self._W - 16
            scaled = px.scaled(max_w, 158, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            self._img_lbl.setPixmap(scaled)
            self._img_lbl.setFixedSize(scaled.width(), scaled.height())
            self.adjustSize()
        self.show()
        self.raise_()
        self._timer.start(6_000)


class SetupOverlay(QWidget):
    """First-run initialization: Gemini API key + operating system."""

    done = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(8, 12, 16, 250);
                border: 1px solid {C.BORDER_B};
                border-radius: 14px;
            }}
        """)

        detected = {"darwin": "mac", "windows": "windows"}.get(_OS.lower(), "linux")
        self._sel_os = detected

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 22, 30, 22)
        layout.setSpacing(8)

        def _lbl(txt, fs=9, bold=False, color=C.TEXT, align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont(_UI_FONT, fs, QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addWidget(_lbl("INITIALISE ASSISTANT", 14, True, C.WHITE))
        layout.addWidget(_lbl("Configure JARVIS before first boot.", 9, color=C.TEXT_DIM))
        layout.addSpacing(6)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep)
        layout.addSpacing(4)

        layout.addWidget(_lbl("GEMINI API KEY", 8, color=C.TEXT_DIM,
                              align=Qt.AlignmentFlag.AlignLeft))
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("AIza…")
        self._key_input.setFont(QFont(_MONO_FONT, 10))
        self._key_input.setFixedHeight(34)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: {C.PANEL}; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 6px; padding: 4px 10px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        layout.addWidget(self._key_input)
        layout.addSpacing(12)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep2)
        layout.addSpacing(4)

        layout.addWidget(_lbl("OPERATING SYSTEM", 8, color=C.TEXT_DIM,
                              align=Qt.AlignmentFlag.AlignLeft))
        det_name = {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[detected]
        layout.addWidget(_lbl(f"Auto-detected: {det_name}", 8, color=C.ACC2,
                              align=Qt.AlignmentFlag.AlignLeft))

        os_row = QHBoxLayout(); os_row.setSpacing(6)
        self._os_btns: dict[str, QPushButton] = {}
        for key, label in [("windows","⊞  Windows"),("mac","  macOS"),("linux","🐧  Linux")]:
            btn = QPushButton(label)
            btn.setFont(QFont(_UI_FONT, 9, QFont.Weight.Bold))
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        layout.addLayout(os_row)
        self._sel(detected)
        layout.addSpacing(12)

        init_btn = QPushButton("▸  INITIALISE SYSTEMS")
        init_btn.setFont(QFont(_UI_FONT, 10, QFont.Weight.Bold))
        init_btn.setFixedHeight(38)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PRI_GHO}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 6px;
            }}
            QPushButton:hover {{ background: {C.PRI_DIM}; color: {C.DARK}; }}
        """)
        init_btn.clicked.connect(self._submit)
        layout.addWidget(init_btn)

    def _sel(self, key: str):
        self._sel_os = key
        pal = {"windows": (C.PRI, "#0b2530"), "mac": (C.ACC2, "#2a2010"),
               "linux": (C.GREEN, "#0c2518")}
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{ background: {fg}; color: {bg};
                        border: none; border-radius: 6px; font-weight: bold; }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{ background: {C.PANEL}; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 6px; }}
                    QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
                """)

    def _submit(self):
        key = self._key_input.text().strip()
        if not key:
            self._key_input.setStyleSheet(
                self._key_input.styleSheet() + f" QLineEdit {{ border: 1px solid {C.RED}; }}")
            return
        self.done.emit(key, self._sel_os)


class HueWheel(QWidget):
    """Circular hue picker for UI accent colour."""

    hue_picked    = pyqtSignal(str)
    hue_committed = pyqtSignal(str)

    _RING = 16

    def __init__(self, initial_hex: str = DEFAULT_UI_COLOR, parent=None):
        super().__init__(parent)
        self.setFixedSize(148, 148)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hue  = 0.55
        self._drag = False
        self.set_color(initial_hex)

    def color(self) -> str:
        return QColor.fromHsvF(self._hue, 1.0, 1.0).name()

    def set_color(self, hex_str: str):
        c = QColor((hex_str or "").strip())
        if c.isValid() and c.hsvHueF() >= 0:
            self._hue = c.hsvHueF()
            self.update()

    def _ring_rect(self) -> QRectF:
        m = self._RING / 2 + 3
        return QRectF(self.rect()).adjusted(m, m, -m, -m)

    def _hue_from_pos(self, pos: QPointF) -> float:
        c  = QRectF(self.rect()).center()
        dx = pos.x() - c.x()
        dy = c.y() - pos.y()
        ang = math.atan2(dy, dx)
        return (ang / (2 * math.pi)) % 1.0

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect   = self._ring_rect()
        center = rect.center()

        grad = QConicalGradient(center, 0)
        for i in range(0, 361, 20):
            grad.setColorAt(i / 360.0, QColor.fromHsvF((i % 360) / 360.0, 1.0, 1.0))
        p.setPen(QPen(QBrush(grad), self._RING))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect)

        preview = QColor.fromHsvF(self._hue, 1.0, 1.0)
        inner   = rect.adjusted(30, 30, -30, -30)
        p.setPen(QPen(qcol(C.BORDER_B), 1))
        p.setBrush(QBrush(preview))
        p.drawEllipse(inner)

        r   = rect.width() / 2
        ang = self._hue * 2 * math.pi
        hx  = center.x() + r * math.cos(ang)
        hy  = center.y() - r * math.sin(ang)
        p.setPen(QPen(QColor("#07090b"), 2))
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(QPointF(hx, hy), 7.5, 7.5)

    def mousePressEvent(self, e):
        self._drag = True
        self._hue  = self._hue_from_pos(e.position())
        self.update()
        self.hue_picked.emit(self.color())

    def mouseMoveEvent(self, e):
        if self._drag:
            self._hue = self._hue_from_pos(e.position())
            self.update()
            self.hue_picked.emit(self.color())

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.hue_committed.emit(self.color())


class CustomizeOverlay(QWidget):
    """Floating overlay — change assistant name, user name and UI colour."""

    saved = pyqtSignal(str, str, str)
    _OW, _OH = 400, 500

    def __init__(self, assistant_name="JARVIS", user_name="",
                 ui_color=DEFAULT_UI_COLOR, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            CustomizeOverlay {{
                background: rgba(8, 12, 16, 250);
                border: 1px solid {C.BORDER_B};
                border-radius: 14px;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(8)

        def _lbl(txt, fs=9, bold=False, color=C.TEXT, align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt); w.setAlignment(align)
            w.setFont(QFont(_UI_FONT, fs, QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        _fs = (f"QLineEdit {{ background: {C.PANEL}; color: {C.TEXT}; "
               f"border: 1px solid {C.BORDER}; border-radius: 6px; padding: 4px 10px; }}"
               f"QLineEdit:focus {{ border: 1px solid {C.PRI}; }}")

        lay.addWidget(_lbl("CUSTOMISE ASSISTANT", 12, True, C.WHITE))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        lay.addWidget(_lbl("ASSISTANT NAME", 8, color=C.TEXT_DIM,
                           align=Qt.AlignmentFlag.AlignLeft))
        self._name_input = QLineEdit(assistant_name)
        self._name_input.setFont(QFont(_UI_FONT, 10))
        self._name_input.setFixedHeight(32)
        self._name_input.setStyleSheet(_fs)
        lay.addWidget(self._name_input)

        lay.addSpacing(4)
        lay.addWidget(_lbl("YOUR NAME  (optional)", 8, color=C.TEXT_DIM,
                           align=Qt.AlignmentFlag.AlignLeft))
        self._user_input = QLineEdit(user_name)
        self._user_input.setPlaceholderText("e.g.  Mark")
        self._user_input.setFont(QFont(_UI_FONT, 10))
        self._user_input.setFixedHeight(32)
        self._user_input.setStyleSheet(_fs)
        lay.addWidget(self._user_input)

        lay.addSpacing(4)
        clr_hdr = QHBoxLayout()
        clr_hdr.addWidget(_lbl("UI COLOUR", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        clr_hdr.addStretch()
        df_btn = QPushButton("DEFAULT")
        df_btn.setFixedSize(64, 20)
        df_btn.setFont(QFont(_MONO_FONT, 7, QFont.Weight.Bold))
        df_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        df_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 4px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        df_btn.clicked.connect(lambda: self._set_color(DEFAULT_UI_COLOR))
        clr_hdr.addWidget(df_btn)
        lay.addLayout(clr_hdr)

        self._initial_color = (ui_color or DEFAULT_UI_COLOR).strip().lower()
        self._sel_color     = self._initial_color
        self.on_preview     = None

        self._wheel = HueWheel(self._sel_color)
        wheel_row = QHBoxLayout()
        wheel_row.addStretch(); wheel_row.addWidget(self._wheel); wheel_row.addStretch()
        lay.addLayout(wheel_row)
        self._wheel.hue_picked.connect(self._on_wheel_pick)
        self._wheel.hue_committed.connect(self._on_wheel_commit)

        self._hex_input = QLineEdit(self._sel_color)
        self._hex_input.setPlaceholderText("#3ec8ff   (custom hex colour)")
        self._hex_input.setFont(QFont(_MONO_FONT, 10))
        self._hex_input.setFixedHeight(28)
        self._hex_input.setStyleSheet(_fs)
        self._hex_input.textEdited.connect(self._on_hex_edited)
        lay.addWidget(self._hex_input)

        lay.addSpacing(6)
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)

        save_btn = QPushButton("▸  APPLY CHANGES")
        save_btn.setFixedHeight(34)
        save_btn.setFont(QFont(_UI_FONT, 9, QFont.Weight.Bold))
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(f"""
            QPushButton {{ background: {C.PRI_GHO}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 6px; }}
            QPushButton:hover {{ background: {C.PRI_DIM}; color: {C.DARK}; }}
        """)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        cancel_btn = QPushButton("CANCEL")
        cancel_btn.setFixedHeight(34)
        cancel_btn.setFont(QFont(_UI_FONT, 9))
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 6px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(cancel_btn)
        lay.addLayout(btn_row)

    def _set_color(self, hx: str, update_wheel: bool = True, preview: bool = True):
        self._sel_color = hx.strip().lower()
        self._hex_input.blockSignals(True)
        self._hex_input.setText(self._sel_color)
        self._hex_input.blockSignals(False)
        if update_wheel:
            self._wheel.set_color(self._sel_color)
        if preview and self.on_preview:
            self.on_preview(self._sel_color)

    def _on_wheel_pick(self, hx: str):
        self._sel_color = hx
        self._hex_input.blockSignals(True)
        self._hex_input.setText(hx)
        self._hex_input.blockSignals(False)

    def _on_wheel_commit(self, hx: str):
        self._set_color(hx, update_wheel=False)

    def _on_hex_edited(self, text: str):
        t = text.strip().lower()
        if t.startswith("#") and len(t) == 7:
            try:
                int(t[1:], 16)
            except ValueError:
                return
            self._set_color(t, update_wheel=True, preview=True)

    def _cancel(self):
        if self.on_preview and self._sel_color != self._initial_color:
            self.on_preview(self._initial_color)
        self.hide()

    def _save(self):
        name = self._name_input.text().strip() or "JARVIS"
        user = self._user_input.text().strip()
        self.saved.emit(name, user, self._sel_color or DEFAULT_UI_COLOR)
        self.hide()


class ClipboardPanel(QWidget):
    """Floating panel shown when text is copied — quick assistant actions."""

    action_requested = pyqtSignal(str)
    _W, _H = 326, 112

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            ClipboardPanel {{
                background: rgba(8, 12, 16, 248);
                border: 1px solid {C.BORDER_B};
                border-radius: 12px;
            }}
        """)
        self.setFixedWidth(self._W)
        self._clip_text = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 7)
        lay.setSpacing(4)

        hdr = QHBoxLayout(); hdr.setSpacing(4)
        icon_lbl = QLabel("◈  CLIPBOARD DETECTED")
        icon_lbl.setFont(QFont(_MONO_FONT, 7, QFont.Weight.Bold))
        icon_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent;")
        hdr.addWidget(icon_lbl); hdr.addStretch()
        x_btn = QPushButton("✕")
        x_btn.setFixedSize(16, 16)
        x_btn.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        x_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        x_btn.clicked.connect(self.hide)
        hdr.addWidget(x_btn)
        lay.addLayout(hdr)

        self._preview = QLabel()
        self._preview.setFont(QFont(_UI_FONT, 8))
        self._preview.setStyleSheet(f"""
            color: {C.TEXT}; background: {C.PANEL2};
            border: 1px solid {C.BORDER}; border-radius: 6px; padding: 4px 8px;
        """)
        self._preview.setWordWrap(False)
        self._preview.setFixedHeight(28)
        lay.addWidget(self._preview)

        btn_row = QHBoxLayout(); btn_row.setSpacing(4)
        _bs = (f"QPushButton {{ background: {C.PANEL2}; color: {C.TEXT_MED}; "
               f"border: 1px solid {C.BORDER}; border-radius: 4px; }}"
               f"QPushButton:hover {{ color: {C.PRI}; border-color: {C.BORDER_B}; }}")
        for label, cmd_fmt in [
            ("TRANSLATE", "Translate this text to English: {text}"),
            ("SUMMARISE", "Summarise this: {text}"),
            ("EXPLAIN",   "Explain this: {text}"),
            ("FIX",       "Fix grammar and spelling: {text}"),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(22)
            b.setFont(QFont(_MONO_FONT, 7, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(_bs)
            b.clicked.connect(lambda _, c=cmd_fmt: self._trigger(c))
            btn_row.addWidget(b)
        lay.addLayout(btn_row)

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.hide)
        self.hide()

    def _trigger(self, cmd_fmt: str):
        if self._clip_text:
            self.action_requested.emit(cmd_fmt.format(text=self._clip_text[:800]))
        self.hide()

    def show_clipboard(self, text: str):
        self._clip_text = text
        preview = text[:58].replace('\n', ' ')
        if len(text) > 58:
            preview += "…"
        self._preview.setText(f'"{preview}"')
        self.show(); self.raise_()
        self._dismiss_timer.start(8000)


class RemoteKeyOverlay(QWidget):
    """Floating overlay — QR code for phone pairing + manual key fallback."""

    closed = pyqtSignal()

    _OW, _OH = 400, 465

    def __init__(self, url: str, key: str, auto_login_url: str = "",
                 manual_url: str = "", expiry_secs: int = 600, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            RemoteKeyOverlay {{
                background: rgba(7, 11, 15, 0.96);
                border: 1px solid {C.BORDER_B};
                border-radius: 16px;
            }}
        """)
        self._expiry         = time.time() + expiry_secs
        self._on_new_key     = None
        self._auto_login_url = auto_login_url
        self._manual_url     = manual_url or url

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(5)

        def _lbl(txt, fs=9, bold=False, color=C.TEXT,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont(_UI_FONT, fs, QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            w.setWordWrap(True)
            return w

        lay.addWidget(_lbl("REMOTE ACCESS", 13, True, C.WHITE))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep)

        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setFixedSize(176, 176)
        self._qr_label.setStyleSheet("background: white; border-radius: 10px; padding: 4px;")
        qr_row = QHBoxLayout()
        qr_row.addStretch(); qr_row.addWidget(self._qr_label); qr_row.addStretch()
        lay.addLayout(qr_row)

        self._update_qr(auto_login_url)

        lay.addWidget(_lbl("Scan with your phone to connect instantly", 8, color=C.TEXT_DIM))

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_lbl("Or enter manually:", 7, color=C.TEXT_DIM,
                           align=Qt.AlignmentFlag.AlignLeft))

        self._url_lbl = QLabel(self._manual_url)
        self._url_lbl.setFont(QFont(_MONO_FONT, 8))
        self._url_lbl.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        self._url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._url_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self._url_lbl)

        self._key_lbl = QLabel(key)
        self._key_lbl.setFont(QFont(_MONO_FONT, 28, QFont.Weight.Bold))
        self._key_lbl.setStyleSheet(f"""
            color: {C.ACC}; background: {C.PANEL2};
            border: 1px solid {C.BORDER_B}; border-radius: 8px;
            padding: 6px 4px; letter-spacing: 10px;
        """)
        self._key_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._key_lbl)

        self._timer_lbl = QLabel()
        self._timer_lbl.setFont(QFont(_MONO_FONT, 8))
        self._timer_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._timer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._timer_lbl)

        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        new_btn = QPushButton("NEW KEY")
        new_btn.setFixedHeight(32)
        new_btn.setFont(QFont(_UI_FONT, 8, QFont.Weight.Bold))
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.setStyleSheet(f"""
            QPushButton {{ background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 6px; }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        new_btn.clicked.connect(self._refresh_key)
        btn_row.addWidget(new_btn)

        close_btn = QPushButton("DISMISS")
        close_btn.setFixedHeight(32)
        close_btn.setFont(QFont(_UI_FONT, 8, QFont.Weight.Bold))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 6px; }}
            QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
        """)
        close_btn.clicked.connect(self._do_close)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

        self._ctimer = QTimer(self)
        self._ctimer.timeout.connect(self._tick)
        self._ctimer.start(1000)
        self._tick()

    def set_new_key_callback(self, fn) -> None:
        self._on_new_key = fn

    def _update_qr(self, url: str) -> None:
        if not url:
            self._qr_label.setText("—")
            return
        try:
            import qrcode as _qrmod
            from io import BytesIO
            qr = _qrmod.QRCode(box_size=5, border=2,
                               error_correction=_qrmod.constants.ERROR_CORRECT_M)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap()
            px.loadFromData(buf.getvalue())
            self._qr_label.setPixmap(
                px.scaled(170, 170, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation))
        except ImportError:
            self._qr_label.setText("pip install\nqrcode[pil]")
            self._qr_label.setFont(QFont(_MONO_FONT, 8))
            self._qr_label.setStyleSheet("color: #888; background: white; border-radius: 10px;")
        except Exception:
            self._qr_label.setText(url[:28])
            self._qr_label.setFont(QFont(_MONO_FONT, 7))
            self._qr_label.setStyleSheet(f"color: {C.PRI}; background: white; border-radius: 10px;")

    def _tick(self):
        remaining = max(0, int(self._expiry - time.time()))
        m, s = divmod(remaining, 60)
        self._timer_lbl.setText(f"Key expires in  {m:02d}:{s:02d}")
        if remaining == 0:
            self._do_close()

    def mark_connected(self) -> None:
        self._ctimer.stop()
        self._key_lbl.setText("CONNECTED")
        self._key_lbl.setStyleSheet(f"""
            color: {C.GREEN}; background: rgba(61,220,151,0.08);
            border: 2px solid rgba(61,220,151,0.4); border-radius: 8px;
            padding: 6px 4px; letter-spacing: 4px;
        """)
        self._qr_label.setText("✓")
        self._qr_label.setFont(QFont(_UI_FONT, 54, QFont.Weight.Bold))
        self._qr_label.setStyleSheet("color: #3ddc97; background: #0c2518; border-radius: 10px;")
        self._timer_lbl.setText("Phone connected — JARVIS ready")
        self._timer_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent;")

    def _refresh_key(self):
        if self._on_new_key:
            result = self._on_new_key()
            if result:
                url    = result[0]
                key    = result[1]
                auto   = result[2] if len(result) >= 3 else ""
                manual = result[3] if len(result) >= 4 else url
                self._manual_url     = manual or url
                self._url_lbl.setText(self._manual_url)
                self._key_lbl.setText(key)
                self._auto_login_url = auto
                self._update_qr(auto or url)
                self._expiry = time.time() + 600
                self._key_lbl.setStyleSheet(f"""
                    color: {C.ACC}; background: {C.PANEL2};
                    border: 1px solid {C.BORDER_B}; border-radius: 8px;
                    padding: 6px 4px; letter-spacing: 10px;
                """)
                self._timer_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
                self._ctimer.start(1000)
                self._tick()

    def _do_close(self):
        self._ctimer.stop()
        self.hide()
        self.closed.emit()


# ══════════════════════════════════════════════════════════════════════════════
#  Main window
# ══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self, face_path: str):
        super().__init__()
        self._face_path = face_path

        _cfg = _read_full_config()
        self._assistant_name: str = (_cfg.get("assistant_name") or "JARVIS").strip()
        _display = self._assistant_name.upper()

        _ui_color = (_cfg.get("ui_color") or "").strip()
        if _ui_color and _ui_color.lower() != DEFAULT_UI_COLOR:
            apply_ui_accent(_ui_color)

        self.setWindowTitle(f"{_display}")
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        # Taskbar/window icon — JARVIS's own mark, not the Python launcher icon.
        try:
            ico = CONFIG_DIR / "jarvis.ico"
            if not ico.exists():
                self._build_jarvis_icon(ico)
            if ico.exists():
                self.setWindowIcon(QIcon(str(ico)))
        except Exception as e:
            print(f"[UI] ⚠️ window icon failed: {e}")

        screen = QApplication.primaryScreen().availableGeometry()
        self.move((screen.width()  - _DEFAULT_W) // 2,
                  (screen.height() - _DEFAULT_H) // 2)

        self.on_text_command   = None
        self.on_remote_clicked = None
        self.on_interrupt      = None
        self._muted            = False
        self._voice_volume     = 1.0
        self._current_file: str | None = None
        self._remote_overlay: RemoteKeyOverlay | None = None
        self._customize_overlay: CustomizeOverlay | None = None

        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(10, 10, 10, 10)
        body.setSpacing(10)

        body.addWidget(self._build_left_panel(), stretch=0)

        # center: core + collapsible content panel
        self.core = JarvisCore(face_path, _display)
        self._content_panel = self._build_content_panel()

        _cam_cont = QWidget()
        _cam_cont.setStyleSheet("background: #050709;")
        _cam_v = QVBoxLayout(_cam_cont)
        _cam_v.setContentsMargins(0, 0, 0, 0)
        _cam_v.setSpacing(0)
        _cam_hdr = QHBoxLayout()
        _cam_hdr.setContentsMargins(12, 6, 12, 6)
        _cam_title = QLabel("◈  CAMERA FEED")
        _cam_title.setFont(QFont(_MONO_FONT, 8, QFont.Weight.Bold))
        _cam_title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        _cam_hdr.addWidget(_cam_title)
        _cam_hdr.addStretch()
        _cam_x = QPushButton("✕  CLOSE")
        _cam_x.setFont(QFont(_MONO_FONT, 8, QFont.Weight.Bold))
        _cam_x.setCursor(Qt.CursorShape.PointingHandCursor)
        _cam_x.setStyleSheet(f"""
            QPushButton {{ color: {C.TEXT_DIM}; background: transparent;
                border: none; padding: 2px 6px; }}
            QPushButton:hover {{ color: {C.PRI}; }}
        """)
        _cam_x.clicked.connect(self.stop_camera_stream)
        _cam_hdr.addWidget(_cam_x)
        _cam_v.addLayout(_cam_hdr)
        self._cam_live_lbl = QLabel()
        self._cam_live_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cam_live_lbl.setStyleSheet("background: transparent;")
        self._cam_live_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        _cam_v.addWidget(self._cam_live_lbl, stretch=1)

        self._hud_cam_stack = QStackedWidget()
        self._hud_cam_stack.addWidget(self.core)
        self._hud_cam_stack.addWidget(_cam_cont)

        self._center_split = QSplitter(Qt.Orientation.Vertical)
        self._center_split.setStyleSheet(f"""
            QSplitter::handle {{ background: {C.BORDER}; height: 3px; }}
            QSplitter::handle:hover {{ background: {C.PRI_DIM}; }}
        """)
        self._center_split.addWidget(self._hud_cam_stack)
        self._center_split.addWidget(self._content_panel)
        self._center_split.setStretchFactor(0, 3)
        self._center_split.setStretchFactor(1, 1)
        self._center_split.setCollapsible(0, False)
        body.addWidget(self._center_split, stretch=5)

        body.addWidget(self._build_right_panel(), stretch=0)

        root.addLayout(body, stretch=1)
        root.addWidget(self._build_command_bar())

        self._quick_drawer = self._build_quick_drawer()
        self._update_autostart_btn(self._check_autostart())
        from memory.config_manager import get_brief_enabled as _gbe
        self._update_brief_btn(_gbe())

        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)
        self._update_metrics()

        self._log_sig.connect(self._activity.append_log)
        self._state_sig.connect(self._apply_state)
        self._content_sig.connect(self._show_content)
        self._reconfig_sig.connect(self._show_setup)
        self._camera_sig.connect(self._show_camera_frame)
        self._cam_stream_sig.connect(self._on_cam_stream)
        self._cam_frame_sig.connect(self._on_cam_frame)
        self._clipboard_sig.connect(self._show_clipboard_panel)
        self._cam_stop = threading.Event()

        self._cam_preview = _CameraPreview(self.centralWidget())
        self._clipboard_panel = ClipboardPanel(self.centralWidget())
        self._clipboard_panel.action_requested.connect(self._on_clipboard_action)
        QApplication.clipboard().dataChanged.connect(self._on_clipboard_changed)

        self._overlay: SetupOverlay | None = None
        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_full = QShortcut(QKeySequence("F11"), self)
        sc_full.activated.connect(self._toggle_fullscreen)
        sc_intr = QShortcut(QKeySequence("Escape"), self)
        sc_intr.activated.connect(self._do_interrupt)

    # ── signals ──────────────────────────────────────────────────────────────
    _state_sig     = pyqtSignal(str)
    _log_sig       = pyqtSignal(str)
    _content_sig   = pyqtSignal(str, str)
    _reconfig_sig  = pyqtSignal()
    _camera_sig    = pyqtSignal(bytes)
    _cam_stream_sig = pyqtSignal(bool)
    _cam_frame_sig  = pyqtSignal(bytes)
    _clipboard_sig  = pyqtSignal(str)

    # ── top bar ─────────────────────────────────────────────────────────────
    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(52)
        w.setStyleSheet(f"background: {C.DARK}; border-bottom: 1px solid {C.BORDER_B};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(18, 0, 18, 0)

        mark = QLabel("◈")
        mark.setFont(QFont(_UI_FONT, 15, QFont.Weight.Bold))
        mark.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(mark)

        self._title_lbl = QLabel(self._assistant_name.upper())
        self._title_lbl.setFont(QFont(_UI_FONT, 13, QFont.Weight.DemiBold))
        self._title_lbl.setStyleSheet(f"color: {C.WHITE}; background: transparent;")
        lay.addWidget(self._title_lbl)

        self._sub_lbl = QLabel(
            "Just A Rather Very Intelligent System"
            if self._assistant_name.upper() in ("JARVIS", "J.A.R.V.I.S")
            else "Personal AI Assistant"
        )
        self._sub_lbl.setFont(QFont(_UI_FONT, 7))
        self._sub_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        lay.addSpacing(10)
        lay.addWidget(self._sub_lbl)

        lay.addStretch()

        right = QHBoxLayout()
        right.setSpacing(10)
        self._status_lbl = QLabel("●  STANDBY")
        self._status_lbl.setFont(QFont(_UI_FONT, 8, QFont.Weight.Bold))
        self._status_lbl.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        right.addWidget(self._status_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color: {C.BORDER};")
        right.addWidget(sep)

        self._date_lbl = QLabel("")
        self._date_lbl.setFont(QFont(_UI_FONT, 8))
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        right.addWidget(self._date_lbl)

        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setFont(QFont(_MONO_FONT, 10, QFont.Weight.Bold))
        self._clock_lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        right.addWidget(self._clock_lbl)

        gear = QPushButton("⚙")
        gear.setFixedSize(28, 28)
        gear.setFont(QFont(_UI_FONT, 12))
        gear.setCursor(Qt.CursorShape.PointingHandCursor)
        gear.setToolTip("Settings & Controls")
        gear.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 6px; }}
            QPushButton:hover {{ color: {C.PRI}; border-color: {C.PRI_DIM}; }}
        """)
        gear.clicked.connect(self._toggle_drawer)
        gear.setCheckable(True)
        self._drawer_btn = gear
        right.addWidget(gear)

        lay.addLayout(right)
        return w

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y"))

    # ── left panel — system metrics ─────────────────────────────────────────
    def _build_left_panel(self) -> QWidget:
        panel = ModernPanel("System", radius=12)
        panel.setFixedWidth(_LEFT_W)

        self._metric_cpu = SystemMetric("CPU", C.PRI)
        self._metric_mem = SystemMetric("MEM", C.PRI_DIM)
        self._metric_net = SystemMetric("NET", C.TEXT_MED)
        self._metric_gpu = SystemMetric("GPU", C.PRI_DIM)
        self._metric_tmp = SystemMetric("TMP", C.TEXT_MED, unit="°C")
        for m in [self._metric_cpu, self._metric_mem, self._metric_net,
                  self._metric_gpu, self._metric_tmp]:
            panel.addWidget(m)

        panel.addStretch(1)

        info = QLabel("UPTIME  --:--\nPROCESS  --")
        info.setObjectName("info")
        info.setFont(QFont(_MONO_FONT, 7))
        info.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._uptime_lbl = info
        panel.addWidget(info)

        self._proc_lbl = info  # compatibility alias (updated via _update_metrics)

        return panel

    def _update_metrics(self):
        snap = _metrics.snapshot()

        cpu = snap["cpu"]
        self._metric_cpu.set_value(cpu, f"{cpu:.0f}%")

        mem = snap["mem"]
        self._metric_mem.set_value(mem, f"{mem:.0f}%")

        net = snap["net"]
        if net < 1.0:
            net_str = f"{net*1024:.0f}KB"
        else:
            net_str = f"{net:.1f}MB"
        net_pct = min(100, net * 10)
        self._metric_net.set_value(net_pct, net_str)

        gpu = snap["gpu"]
        if gpu >= 0:
            self._metric_gpu.set_value(gpu, f"{gpu:.0f}%")
        else:
            self._metric_gpu.set_value(0, "N/A")

        tmp = snap["tmp"]
        if tmp >= 0:
            self._metric_tmp.set_value(min(100, (tmp / 100) * 100), f"{tmp:.0f}°C")
        else:
            self._metric_tmp.set_value(0, "N/A")

        try:
            boot_t  = psutil.boot_time()
            elapsed = time.time() - boot_t
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            uptime = f"UPTIME  {h:02d}:{m:02d}"
        except Exception:
            uptime = "UPTIME  --:--"

        try:
            proc = f"PROCESS  {len(psutil.pids())}"
        except Exception:
            proc = "PROCESS  --"

        self._uptime_lbl.setText(f"{uptime}\n{proc}")

    # ── right panel — activity + file upload ────────────────────────────────
    def _build_right_panel(self) -> QWidget:
        panel = ModernPanel("", radius=12)
        panel.setFixedWidth(_RIGHT_W)
        lay = panel.layout()
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        title = QLabel("CONVERSATION")
        title.setFont(QFont(_UI_FONT, 8, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; "
                            f"letter-spacing: 1px;")
        lay.addWidget(title)

        self._activity = ActivityPanel()
        lay.addWidget(self._activity, stretch=1)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};")
        lay.addWidget(sep)

        ft = QLabel("FILE INPUT")
        ft.setFont(QFont(_UI_FONT, 8, QFont.Weight.Bold))
        ft.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; "
                         f"letter-spacing: 1px;")
        lay.addWidget(ft)

        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        lay.addWidget(self._drop_zone)

        self._file_hint = QLabel("No file loaded")
        self._file_hint.setFont(QFont(_UI_FONT, 7))
        self._file_hint.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._file_hint.setWordWrap(True)
        lay.addWidget(self._file_hint)

        return panel

    # ── command bar ─────────────────────────────────────────────────────────
    def _build_command_bar(self) -> QWidget:
        self._cmd = CommandBar()
        self._input = self._cmd.input
        self._input.returnPressed.connect(self._send)
        self._cmd.mic_btn.clicked.connect(self._toggle_mute)
        self._cmd.interrupt_btn.clicked.connect(self._do_interrupt)
        self._cmd.volume.valueChanged.connect(self._on_voice_volume)
        self._mic_btn = self._cmd.mic_btn
        self._interrupt_btn = self._cmd.interrupt_btn
        return self._cmd

    # ── content panel (web results / briefings) ─────────────────────────────
    def _build_content_panel(self) -> QWidget:
        w = QWidget()
        w.setObjectName("ContentPanel")
        w.setStyleSheet(f"""
            QWidget#ContentPanel {{
                background: {C.PANEL};
                border-top: 1px solid {C.BORDER_B};
                border-radius: 0 0 12px 12px;
            }}
        """)
        w.hide()

        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 8, 14, 10)
        lay.setSpacing(6)

        hdr = QHBoxLayout(); hdr.setSpacing(6)
        dot = QLabel("◈")
        dot.setFont(QFont(_MONO_FONT, 9, QFont.Weight.Bold))
        dot.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(dot)

        self._content_title_lbl = QLabel("BRIEFING")
        self._content_title_lbl.setFont(QFont(_MONO_FONT, 8, QFont.Weight.Bold))
        self._content_title_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(self._content_title_lbl)
        hdr.addStretch()

        self._content_ts_lbl = QLabel("")
        self._content_ts_lbl.setFont(QFont(_MONO_FONT, 7))
        self._content_ts_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        hdr.addWidget(self._content_ts_lbl)

        dismiss = QPushButton("DISMISS  ✕")
        dismiss.setFont(QFont(_MONO_FONT, 7))
        dismiss.setFixedHeight(18)
        dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 4px; padding: 0 5px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        dismiss.clicked.connect(w.hide)
        hdr.addWidget(dismiss)
        lay.addLayout(hdr)

        self._content_display = QTextEdit()
        self._content_display.setReadOnly(True)
        self._content_display.setFont(QFont(_UI_FONT, 9))
        self._content_display.setMinimumHeight(60)
        self._content_display.setStyleSheet(f"""
            QTextEdit {{
                background: {C.DARK}; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 8px; padding: 8px 10px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{ background: transparent; width: 6px; }}
            QScrollBar::handle:vertical {{ background: {C.BORDER_B}; border-radius: 3px; }}
        """)
        lay.addWidget(self._content_display)
        return w

    def _show_content(self, title: str, text: str):
        self._content_title_lbl.setText(title.upper()[:48])
        self._content_ts_lbl.setText(time.strftime("%H:%M:%S"))
        self._content_display.setPlainText(text)
        self._content_display.moveCursor(
            self._content_display.textCursor().MoveOperation.Start)
        first_show = not self._content_panel.isVisible()
        self._content_panel.show()
        if first_show:
            total = self._center_split.height()
            self._center_split.setSizes([max(total - 220, 120), 220])

    # ── quick drawer ────────────────────────────────────────────────────────
    def _build_quick_drawer(self) -> QWidget:
        _BTN_PRI = f"""
            QPushButton {{ background: {C.PRI_GHO}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 6px;
                text-align: left; padding: 0 10px; }}
            QPushButton:hover {{ background: {C.PRI_DIM}; color: {C.DARK}; }}
        """
        _BTN_DIM = f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 6px;
                text-align: left; padding: 0 10px; }}
            QPushButton:hover {{ color: {C.PRI}; border-color: {C.BORDER_B}; }}
        """

        w = QWidget(self.centralWidget())
        w.setObjectName("QuickDrawer")
        w.setStyleSheet(f"""
            QWidget#QuickDrawer {{
                background: {C.DARK}; border: 1px solid {C.BORDER_B};
                border-radius: 0 0 10px 10px;
            }}
        """)
        w.hide()

        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(5)

        hdr = QLabel("CONTROLS")
        hdr.setFont(QFont(_MONO_FONT, 7, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; "
                          f"border-bottom: 1px solid {C.BORDER}; padding-bottom: 4px;")
        lay.addWidget(hdr)

        remote_btn = QPushButton("◉  REMOTE CONTROL")
        remote_btn.setFixedHeight(30)
        remote_btn.setFont(QFont(_UI_FONT, 8, QFont.Weight.Bold))
        remote_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remote_btn.setStyleSheet(_BTN_PRI)
        remote_btn.clicked.connect(self._open_remote)
        lay.addWidget(remote_btn)

        fs_btn = QPushButton("⛶  FULLSCREEN  [F11]")
        fs_btn.setFixedHeight(26)
        fs_btn.setFont(QFont(_UI_FONT, 7))
        fs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fs_btn.setStyleSheet(_BTN_DIM)
        fs_btn.clicked.connect(self._toggle_fullscreen)
        lay.addWidget(fs_btn)

        sc_btn = QPushButton("⊞  CREATE DESKTOP SHORTCUT")
        sc_btn.setFixedHeight(26)
        sc_btn.setFont(QFont(_UI_FONT, 7))
        sc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sc_btn.setStyleSheet(_BTN_DIM)
        sc_btn.clicked.connect(self._create_desktop_shortcut)
        lay.addWidget(sc_btn)

        self._autostart_btn = QPushButton("◉  AUTO-START: OFF")
        self._autostart_btn.setFixedHeight(26)
        self._autostart_btn.setFont(QFont(_UI_FONT, 7))
        self._autostart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._autostart_btn.clicked.connect(self._toggle_autostart)
        lay.addWidget(self._autostart_btn)

        cust_btn = QPushButton("⚙  CUSTOMISE ASSISTANT")
        cust_btn.setFixedHeight(26)
        cust_btn.setFont(QFont(_UI_FONT, 7))
        cust_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cust_btn.setStyleSheet(_BTN_DIM)
        cust_btn.clicked.connect(self._open_customize)
        lay.addWidget(cust_btn)

        self._brief_btn = QPushButton()
        self._brief_btn.setFixedHeight(26)
        self._brief_btn.setFont(QFont(_UI_FONT, 7))
        self._brief_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._brief_btn.clicked.connect(self._toggle_brief)
        lay.addWidget(self._brief_btn)

        w.adjustSize()
        return w

    def _toggle_drawer(self, checked: bool):
        if checked:
            self._position_quick_drawer()
            self._quick_drawer.show()
            self._quick_drawer.raise_()
        else:
            self._quick_drawer.hide()

    def _position_quick_drawer(self):
        if not hasattr(self, '_quick_drawer'):
            return
        _W = 230
        self._quick_drawer.setFixedWidth(_W)
        self._quick_drawer.adjustSize()
        self._quick_drawer.setGeometry(
            18, 52, _W, self._quick_drawer.sizeHint().height())

    # ── input / mute / interrupt / volume ───────────────────────────────────
    def _send(self):
        txt = self._input.text().strip()
        if not txt:
            return
        self._input.clear()
        self._activity.append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _do_interrupt(self):
        if self.on_interrupt:
            self.on_interrupt()

    def _on_voice_volume(self, pct: int):
        self._voice_volume = pct / 100.0

    def _toggle_mute(self):
        self._muted = not self._muted
        self.core.muted = self._muted
        self._mic_btn.set_muted(self._muted)
        if self._muted:
            self._apply_state("MUTED")
            self._activity.append_log("SYS: Microphone muted.")
        else:
            self._apply_state("LISTENING")
            self._activity.append_log("SYS: Microphone active.")

    def _apply_state(self, state: str):
        self.core.state    = state
        self.core.speaking = (state == "SPEAKING")
        _state_lbl, _state_col = self.core._status_label()
        if hasattr(self, "_status_lbl"):
            self._status_lbl.setText(f"●  {_state_lbl}")
            self._status_lbl.setStyleSheet(f"color: {_state_col}; background: transparent;")

    # ── config / setup ──────────────────────────────────────────────────────
    def _check_config(self) -> bool:
        if not API_FILE.exists():
            return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            return bool(d.get("gemini_api_key")) and bool(d.get("os_system"))
        except Exception:
            return False

    def _show_setup(self):
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 460, 390
        ov.setGeometry((cw.width() - ow) // 2, (cw.height() - oh) // 2, ow, oh)
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov

    def _on_setup_done(self, key: str, os_name: str):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        API_FILE.write_text(
            json.dumps({"gemini_api_key": key, "os_system": os_name}, indent=4),
            encoding="utf-8")
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("LISTENING")
        self._assistant_name = _read_full_config().get("assistant_name", "JARVIS") or "JARVIS"
        self._activity.append_log("SYS: Initialised. JARVIS online.")

    # ── camera stream ───────────────────────────────────────────────────────
    def _show_camera_frame(self, img_bytes: bytes):
        self._cam_preview.show_frame(img_bytes)
        cw = self.centralWidget()
        pw = _CameraPreview._W
        ph = self._cam_preview.height()
        self._cam_preview.setGeometry(cw.width() - _RIGHT_W - pw - 24,
                                      cw.height() - ph - 80, pw, ph)

    def _on_cam_stream(self, start: bool) -> None:
        if start:
            self._hud_cam_stack.setCurrentIndex(1)
        else:
            self._hud_cam_stack.setCurrentIndex(0)
            self._cam_live_lbl.clear()

    def _on_cam_frame(self, data: bytes) -> None:
        px = QPixmap()
        px.loadFromData(data)
        if not px.isNull():
            w, h = self._cam_live_lbl.width(), self._cam_live_lbl.height()
            if w > 1 and h > 1:
                self._cam_live_lbl.setPixmap(
                    px.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation))

    def start_camera_stream(self) -> None:
        self._cam_stop.clear()
        self._cam_stream_sig.emit(True)
        t = threading.Thread(target=self._cam_loop, daemon=True, name="cam-stream")
        t.start()

    def _cam_loop(self) -> None:
        try:
            import cv2
            cam_idx = 0
            try:
                cfg = json.loads((CONFIG_DIR / "api_keys.json").read_text())
                cam_idx = int(cfg.get("camera_index", 0))
            except Exception:
                pass
            try:
                backend = cv2.CAP_DSHOW if _OS == "Windows" else cv2.CAP_ANY
            except AttributeError:
                backend = 0
            cap = cv2.VideoCapture(cam_idx, backend)
            if not cap.isOpened():
                cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                return
            for _ in range(5):
                cap.read()
            while not self._cam_stop.wait(0.033) and cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
                    self._cam_frame_sig.emit(buf.tobytes())
            cap.release()
        except Exception as e:
            print(f"[Camera] Stream error: {e}")
        finally:
            self._cam_stream_sig.emit(False)

    def stop_camera_stream(self) -> None:
        self._cam_stop.set()

    # ── icon + desktop shortcut ─────────────────────────────────────────────
    @staticmethod
    def _build_jarvis_icon(out_path: Path) -> bool:
        try:
            import math
            import PIL.Image
            import PIL.ImageDraw
            import PIL.ImageFilter
        except ImportError:
            return False

        CYAN  = (62, 200, 255)
        DIM   = (30, 100, 130)
        DARK  = (7, 10, 13)
        GLOW  = (50, 150, 190)
        WHITE = (230, 244, 255)

        def _render(sz: int) -> PIL.Image.Image:
            S  = sz * 4
            img = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            d   = PIL.ImageDraw.Draw(img)
            cx = cy = S // 2
            R = S // 2 - 2
            d.ellipse([cx-R, cy-R, cx+R, cy+R], fill=(*DARK, 255))
            lw = max(2, S // 40)
            d.ellipse([cx-R, cy-R, cx+R, cy+R], outline=(*CYAN, 220), width=lw)
            R2 = int(R * 0.72)
            d.ellipse([cx-R2, cy-R2, cx+R2, cy+R2], outline=(*DIM, 180), width=max(1, lw // 2))
            R_inner = int(R * 0.30)
            R_outer = int(R * 0.62)
            spoke_w = max(1, S // 80)
            for i in range(6):
                angle = math.radians(i * 60 - 30)
                x1 = cx + int(R_inner * math.cos(angle))
                y1 = cy + int(R_inner * math.sin(angle))
                x2 = cx + int(R_outer * math.cos(angle))
                y2 = cy + int(R_outer * math.sin(angle))
                d.line([x1, y1, x2, y2], fill=(*GLOW, 200), width=spoke_w)
            Ri = int(R * 0.26)
            d.ellipse([cx-Ri, cy-Ri, cx+Ri, cy+Ri], outline=(*CYAN, 255), width=max(2, lw))
            glow_layer = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            gd = PIL.ImageDraw.Draw(glow_layer)
            Rc = int(R * 0.13)
            gd.ellipse([cx-Rc*2, cy-Rc*2, cx+Rc*2, cy+Rc*2], fill=(*CYAN, 110))
            glow_layer = glow_layer.filter(PIL.ImageFilter.GaussianBlur(S // 14))
            img = PIL.Image.alpha_composite(img, glow_layer)
            d   = PIL.ImageDraw.Draw(img)
            d.ellipse([cx-Rc, cy-Rc, cx+Rc, cy+Rc], fill=(*WHITE, 255))
            return img.resize((sz, sz), PIL.Image.LANCZOS)

        try:
            sizes  = [256, 128, 64, 48, 32, 16]
            frames = [_render(s) for s in sizes]
            frames[0].save(out_path, format="ICO", append_images=frames[1:],
                           sizes=[(s, s) for s in sizes])
            return True
        except Exception as e:
            print(f"[Shortcut] ⚠️  Icon generation failed: {e}")
            return False

    @staticmethod
    def _create_lnk_windows(lnk: str, target: str, args: str,
                             work_dir: str, icon_loc: str) -> None:
        try:
            from win32com.client import Dispatch
            sh = Dispatch("WScript.Shell")
            sc = sh.CreateShortCut(lnk)
            sc.TargetPath       = target
            sc.Arguments        = f'"{args}"'
            sc.WorkingDirectory = work_dir
            sc.Description      = "JARVIS AI Assistant"
            sc.IconLocation     = icon_loc
            sc.save()
            return
        except ImportError:
            pass

        vbs = "\n".join([
            'Set ws = CreateObject("WScript.Shell")',
            f'Set sc = ws.CreateShortcut("{lnk}")',
            f'sc.TargetPath = "{target}"',
            f'sc.Arguments = Chr(34) & "{args}" & Chr(34)',
            f'sc.WorkingDirectory = "{work_dir}"',
            'sc.Description = "JARVIS AI Assistant"',
            f'sc.IconLocation = "{icon_loc}"',
            'sc.Save',
        ])
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=".vbs")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(vbs)
            proc = subprocess.Popen(
                ["wscript.exe", "/nologo", tmp],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            )
            proc.wait(timeout=10)
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    @staticmethod
    def _get_desktop_dir() -> Path:
        home = Path.home()
        _os = platform.system()

        if _os == "Windows":
            try:
                import ctypes
                from ctypes import wintypes

                class _GUID(ctypes.Structure):
                    _fields_ = [("Data1", wintypes.DWORD),
                                ("Data2", wintypes.WORD),
                                ("Data3", wintypes.WORD),
                                ("Data4", ctypes.c_ubyte * 8)]

                fid = _GUID(0xB4BFCC3A, 0xDB2C, 0x424C,
                            (ctypes.c_ubyte * 8)(0xB0, 0x29, 0x7F, 0xE9,
                                                 0x9A, 0x87, 0xC6, 0x41))
                buf = ctypes.c_wchar_p()
                if ctypes.windll.shell32.SHGetKnownFolderPath(
                        ctypes.byref(fid), 0, None, ctypes.byref(buf)) == 0:
                    p = Path(buf.value)
                    ctypes.windll.ole32.CoTaskMemFree(buf)
                    if p.is_dir():
                        return p
            except Exception:
                pass
            try:
                import winreg
                with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion"
                        r"\Explorer\User Shell Folders") as key:
                    val, _t = winreg.QueryValueEx(key, "Desktop")
                p = Path(os.path.expandvars(val))
                if p.is_dir():
                    return p
            except Exception:
                pass

        elif _os == "Linux":
            try:
                out = subprocess.run(["xdg-user-dir", "DESKTOP"],
                                     capture_output=True, text=True, timeout=5)
                p = Path(out.stdout.strip())
                if out.stdout.strip() and p != home and p.is_dir():
                    return p
            except Exception:
                pass
            try:
                cfg = home / ".config" / "user-dirs.dirs"
                for line in cfg.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("XDG_DESKTOP_DIR"):
                        val = line.split("=", 1)[1].strip().strip('"')
                        p = Path(val.replace("$HOME", str(home)))
                        if p != home and p.is_dir():
                            return p
            except Exception:
                pass

        return home / "Desktop"

    def _create_desktop_shortcut(self):
        import stat as _stat
        script  = Path(__file__).resolve().parent / "main.py"
        python  = Path(sys.executable)
        desktop = self._get_desktop_dir()

        ico_path = Path(__file__).resolve().parent / "config" / "jarvis.ico"
        if not ico_path.exists():
            self._build_jarvis_icon(ico_path)

        try:
            _os = platform.system()

            if _os == "Windows":
                pythonw  = python.parent / "pythonw.exe"
                target   = str(pythonw if pythonw.exists() else python)
                lnk      = str(desktop / "JARVIS.lnk")
                icon_loc = str(ico_path) if ico_path.exists() else f"{target},0"
                self._create_lnk_windows(lnk, target, str(script),
                                         str(script.parent), icon_loc)

            elif _os == "Darwin":
                app     = desktop / "JARVIS.app"
                mac_dir = app / "Contents" / "MacOS"
                res_dir = app / "Contents" / "Resources"
                mac_dir.mkdir(parents=True, exist_ok=True)
                res_dir.mkdir(exist_ok=True)

                launcher = mac_dir / "JARVIS"
                launcher.write_text(
                    "#!/usr/bin/env bash\n"
                    f'cd "{script.parent}"\n'
                    f'exec "{python}" "{script}"\n')
                launcher.chmod(launcher.stat().st_mode
                               | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)

                (app / "Contents" / "Info.plist").write_text(
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                    '<plist version="1.0"><dict>\n'
                    '  <key>CFBundleExecutable</key><string>JARVIS</string>\n'
                    '  <key>CFBundleIdentifier</key>'
                    '<string>com.jarvis.assistant</string>\n'
                    '  <key>CFBundleName</key><string>JARVIS</string>\n'
                    '  <key>CFBundlePackageType</key><string>APPL</string>\n'
                    '  <key>CFBundleVersion</key><string>1.0</string>\n'
                    '</dict></plist>\n')

                try:
                    import PIL.Image
                    icns = res_dir / "AppIcon.icns"
                    PIL.Image.open(ico_path).save(icns, format="ICNS")
                    plist = app / "Contents" / "Info.plist"
                    txt = plist.read_text()
                    plist.write_text(
                        txt.replace('</dict></plist>',
                                    '  <key>CFBundleIconFile</key>'
                                    '<string>AppIcon</string>\n</dict></plist>\n'))
                except Exception:
                    pass

            else:
                png_path = ico_path.with_suffix(".png")
                if not png_path.exists() and ico_path.exists():
                    try:
                        import PIL.Image
                        PIL.Image.open(ico_path).resize(
                            (256, 256), PIL.Image.LANCZOS).save(png_path, format="PNG")
                    except Exception:
                        png_path = ico_path

                icon_line = f"Icon={png_path}\n" if png_path.exists() else ""
                desk = desktop / "JARVIS.desktop"
                desk.write_text(
                    "[Desktop Entry]\n"
                    "Name=JARVIS\n"
                    f"Exec={python} {script}\n"
                    f"Path={script.parent}\n"
                    "Type=Application\n"
                    "Terminal=false\n"
                    "Categories=Utility;\n"
                    + icon_line)
                desk.chmod(desk.stat().st_mode | 0o755)

            self._activity.append_log("SYS: Desktop shortcut created.")
        except Exception as e:
            self._activity.append_log(f"ERR: Shortcut failed — {e}")

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cw = self.centralWidget()
        if self._overlay and self._overlay.isVisible():
            ow, oh = 460, 390
            self._overlay.setGeometry((cw.width() - ow) // 2,
                                      (cw.height() - oh) // 2, ow, oh)
        if self._remote_overlay and self._remote_overlay.isVisible():
            ow, oh = RemoteKeyOverlay._OW, RemoteKeyOverlay._OH
            self._remote_overlay.setGeometry((cw.width() - ow) // 2,
                                             (cw.height() - oh) // 2, ow, oh)
        if self._customize_overlay and self._customize_overlay.isVisible():
            ow, oh = CustomizeOverlay._OW, CustomizeOverlay._OH
            self._customize_overlay.setGeometry((cw.width() - ow) // 2,
                                                (cw.height() - oh) // 2, ow, oh)
        pw = _CameraPreview._W
        ph = self._cam_preview.height() or _CameraPreview._H
        self._cam_preview.setGeometry(cw.width() - _RIGHT_W - pw - 24,
                                      cw.height() - ph - 80, pw, ph)
        if hasattr(self, '_clipboard_panel') and self._clipboard_panel.isVisible():
            self._position_clipboard_panel()
        if hasattr(self, '_quick_drawer') and self._quick_drawer.isVisible():
            self._position_quick_drawer()

    # ── file selected ───────────────────────────────────────────────────────
    def _on_file_selected(self, path: str):
        self._current_file = path
        p    = Path(path)
        cat  = _file_category(p)
        icon, _ = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size = _fmt_size(p.stat().st_size)
        self._file_hint.setText(f"{icon}  {p.name}  ·  {size}")
        self._activity.append_log(f"FILE: {p.name} ({size}) loaded")
        if self.on_text_command:
            if cat == "image":
                msg = (
                    f"[FILE_UPLOADED] path={path} | name={p.name} | type=image | size={size} | "
                    f"The user has attached a screenshot/image. Immediately call the file_processor "
                    f"tool with action='analyze' (leave file_path empty — it is already set to the "
                    f"uploaded file). Then speak the analysis result naturally.")
            else:
                msg = (
                    f"[FILE_UPLOADED] path={path} | name={p.name} | "
                    f"type={p.suffix.lstrip('.')} | size={size} | "
                    f"Briefly tell the user you can see the file '{p.name}' "
                    f"({size}) has been uploaded and ask what they'd like to do with it.")
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    # ── remote ──────────────────────────────────────────────────────────────
    def notify_phone_connected(self) -> None:
        if self._remote_overlay and self._remote_overlay.isVisible():
            self._remote_overlay.mark_connected()

    def _open_remote(self):
        if not self.on_remote_clicked:
            self._activity.append_log("SYS: Dashboard not running — remote unavailable.")
            return
        result = self.on_remote_clicked()
        if not result:
            self._activity.append_log("SYS: Could not generate remote key.")
            return
        url    = result[0]
        key    = result[1]
        auto   = result[2] if len(result) >= 3 else ""
        manual = result[3] if len(result) >= 4 else url
        if self._remote_overlay:
            self._remote_overlay._do_close()
        cw  = self.centralWidget()
        ow, oh = RemoteKeyOverlay._OW, RemoteKeyOverlay._OH
        ov  = RemoteKeyOverlay(url, key, auto_login_url=auto, manual_url=manual,
                               expiry_secs=600, parent=cw)
        ov.set_new_key_callback(self.on_remote_clicked)
        ov.setGeometry((cw.width() - ow) // 2, (cw.height() - oh) // 2, ow, oh)
        ov.closed.connect(lambda: setattr(self, '_remote_overlay', None))
        ov.show()
        self._remote_overlay = ov
        self._activity.append_log(f"SYS: Remote key generated — manual: {manual or url}")

    # ── auto-start ──────────────────────────────────────────────────────────
    def _check_autostart(self) -> bool:
        try:
            if _OS == "Windows":
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
                try:
                    winreg.QueryValueEx(key, "JARVIS_AI")
                    return True
                except FileNotFoundError:
                    return False
                finally:
                    winreg.CloseKey(key)
            elif _OS == "Darwin":
                return (Path.home() / "Library" / "LaunchAgents"
                        / "com.jarvis.assistant.plist").exists()
            else:
                return (Path.home() / ".config" / "autostart" / "jarvis.desktop").exists()
        except Exception:
            return False

    def _toggle_autostart(self):
        currently_on = self._check_autostart()
        try:
            script = str(Path(__file__).resolve().parent / "main.py")
            if _OS == "Windows":
                import winreg
                reg = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS)
                if currently_on:
                    winreg.DeleteValue(reg, "JARVIS_AI")
                else:
                    pythonw = Path(sys.executable).parent / "pythonw.exe"
                    exe = str(pythonw if pythonw.exists() else sys.executable)
                    winreg.SetValueEx(reg, "JARVIS_AI", 0, winreg.REG_SZ,
                                      f'"{exe}" "{script}"')
                winreg.CloseKey(reg)
            elif _OS == "Darwin":
                plist_dir = Path.home() / "Library" / "LaunchAgents"
                plist_dir.mkdir(parents=True, exist_ok=True)
                plist = plist_dir / "com.jarvis.assistant.plist"
                if currently_on:
                    plist.unlink(missing_ok=True)
                else:
                    plist.write_text(
                        '<?xml version="1.0" encoding="UTF-8"?>\n'
                        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                        '<plist version="1.0"><dict>\n'
                        '  <key>Label</key><string>com.jarvis.assistant</string>\n'
                        '  <key>ProgramArguments</key><array>\n'
                        f'    <string>{sys.executable}</string>\n'
                        f'    <string>{script}</string>\n'
                        '  </array>\n'
                        '  <key>RunAtLoad</key><true/>\n'
                        '</dict></plist>\n')
            else:
                desk_dir = Path.home() / ".config" / "autostart"
                desk_dir.mkdir(parents=True, exist_ok=True)
                desk = desk_dir / "jarvis.desktop"
                if currently_on:
                    desk.unlink(missing_ok=True)
                else:
                    desk.write_text(
                        "[Desktop Entry]\n"
                        f"Name={self._assistant_name}\n"
                        f"Exec={sys.executable} {script}\n"
                        "Type=Application\nTerminal=false\n"
                        "X-GNOME-Autostart-enabled=true\n")
            enabled = not currently_on
            self._update_autostart_btn(enabled)
            self._activity.append_log(
                f"SYS: Auto-start {'enabled' if enabled else 'disabled'}.")
        except Exception as e:
            self._activity.append_log(f"ERR: Auto-start failed — {e}")

    def _update_autostart_btn(self, enabled: bool):
        if not hasattr(self, '_autostart_btn'):
            return
        if enabled:
            self._autostart_btn.setText("◉  AUTO-START: ON")
            self._autostart_btn.setStyleSheet(f"""
                QPushButton {{ background: #0c2518; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 6px; }}
                QPushButton:hover {{ background: #123024; }}
            """)
        else:
            self._autostart_btn.setText("◉  AUTO-START: OFF")
            self._autostart_btn.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 6px; }}
                QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
            """)

    def _toggle_brief(self):
        from memory.config_manager import get_brief_enabled, save_brief_enabled
        new_val = not get_brief_enabled()
        save_brief_enabled(new_val)
        self._update_brief_btn(new_val)

    def _update_brief_btn(self, enabled: bool):
        if not hasattr(self, '_brief_btn'):
            return
        if enabled:
            self._brief_btn.setText("☀  MORNING BRIEF: ON")
            self._brief_btn.setStyleSheet(f"""
                QPushButton {{ background: #0c2518; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 6px;
                    text-align: left; padding: 0 10px; }}
                QPushButton:hover {{ background: #123024; }}
            """)
        else:
            self._brief_btn.setText("☀  MORNING BRIEF: OFF")
            self._brief_btn.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 6px;
                    text-align: left; padding: 0 10px; }}
                QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
            """)

    # ── customization ───────────────────────────────────────────────────────
    def _open_customize(self):
        cfg = _read_full_config()
        if self._customize_overlay:
            self._customize_overlay.hide()
        cw = self.centralWidget()
        ov = CustomizeOverlay(
            cfg.get("assistant_name", "JARVIS") or "JARVIS",
            cfg.get("user_name", ""),
            cfg.get("ui_color", "") or DEFAULT_UI_COLOR,
            parent=cw)
        ow, oh = CustomizeOverlay._OW, CustomizeOverlay._OH
        oh = min(oh, cw.height() - 16)
        ov.setGeometry((cw.width() - ow) // 2, (cw.height() - oh) // 2, ow, oh)
        ov.on_preview = self._preview_ui_color
        ov.saved.connect(self._apply_name_update)
        ov.show()
        self._customize_overlay = ov

    def _preview_ui_color(self, hex_color: str):
        old = current_palette()
        if apply_ui_accent(hex_color):
            retheme_all_widgets(old, current_palette())

    def _apply_name_update(self, name: str, user_name: str, ui_color: str = ""):
        self._assistant_name = name.strip() or "JARVIS"
        display = self._assistant_name.upper()
        self.setWindowTitle(display)
        self._title_lbl.setText(display)
        if display in ("JARVIS", "J.A.R.V.I.S"):
            self._sub_lbl.setText("Just A Rather Very Intelligent System")
        else:
            self._sub_lbl.setText("Personal AI Assistant")
        self._activity._ai_name_lc = self._assistant_name.lower()
        self.core._assistant_name = display

        color_changed = False
        if ui_color:
            old = current_palette()
            if apply_ui_accent(ui_color):
                retheme_all_widgets(old, current_palette())
                color_changed = old["PRI"] != C.PRI

        try:
            data = _read_full_config()
            data["assistant_name"] = self._assistant_name
            data["user_name"] = user_name.strip()
            if ui_color:
                data["ui_color"] = ui_color.strip().lower()
            API_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")
            self._activity.append_log(f"SYS: Identity updated — {display}")
            if color_changed:
                self._activity.append_log(f"SYS: UI colour applied — {ui_color}")
        except Exception as e:
            self._activity.append_log(f"ERR: Config save failed — {e}")

    # ── clipboard ───────────────────────────────────────────────────────────
    def _on_clipboard_changed(self):
        try:
            text = QApplication.clipboard().text().strip()
            if len(text) >= 10:
                self._clipboard_sig.emit(text)
        except Exception:
            pass

    def _show_clipboard_panel(self, text: str):
        self._clipboard_panel.show_clipboard(text)
        self._position_clipboard_panel()

    def _position_clipboard_panel(self):
        cw = self.centralWidget()
        pw = ClipboardPanel._W
        ph = self._clipboard_panel.sizeHint().height() or ClipboardPanel._H
        x = (cw.width() - pw) // 2
        y = cw.height() - ph - 70
        self._clipboard_panel.setGeometry(x, y, pw, ph)
        self._clipboard_panel.raise_()

    def _on_clipboard_action(self, cmd: str):
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(cmd,), daemon=True).start()


class _GlobalHotkeyFilter(QAbstractNativeEventFilter):
    """System-wide F4 hotkey that toggles the mic mute from any application.

    QShortcut / keyPressEvent only fire when JARVIS has focus. This registers
    a global hotkey via the Win32 RegisterHotKey API (ctypes — no new
    dependency) and receives WM_HOTKEY through Qt's native event filter, so it
    keeps working when JARVIS is minimised or another app is focused.
    """

    _WM_HOTKEY = 0x0312
    _VK_F4 = 0x73
    _HOTKEY_ID = 0xF4

    def __init__(self, callback):
        super().__init__()
        self._callback = callback
        self._registered = False
        self._msg_type = None

    def register(self) -> bool:
        if platform.system() != "Windows":
            return False
        try:
            import ctypes
            from ctypes import wintypes

            class _POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

            class _MSG(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND),
                    ("message", wintypes.UINT),
                    ("wParam", ctypes.c_size_t),
                    ("lParam", ctypes.c_size_t),
                    ("time", wintypes.DWORD),
                    ("pt", _POINT),
                ]

            self._msg_type = _MSG

            user32 = ctypes.windll.user32
            user32.RegisterHotKey.argtypes = [
                wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
            user32.RegisterHotKey.restype = wintypes.BOOL
            self._registered = bool(
                user32.RegisterHotKey(None, self._HOTKEY_ID, 0, self._VK_F4))
        except Exception as e:
            print(f"[UI] ⚠️ global hotkey register failed: {e}")
            self._registered = False
        return self._registered

    def unregister(self) -> None:
        if not self._registered:
            return
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.UnregisterHotKey.restype = wintypes.BOOL
            user32.UnregisterHotKey(None, self._HOTKEY_ID)
        except Exception:
            pass
        self._registered = False

    def nativeEventFilter(self, eventType, message):
        if not self._registered or self._msg_type is None:
            return False, 0
        try:
            msg = self._msg_type.from_address(int(message))
            if msg.message == self._WM_HOTKEY and int(msg.wParam) == self._HOTKEY_ID:
                try:
                    self._callback()
                except Exception as e:
                    print(f"[UI] ⚠️ hotkey callback failed: {e}")
                return True, 0
        except Exception:
            pass
        return False, 0


class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app

    def mainloop(self):
        self._app.exec()

    def protocol(self, *_):
        pass


def _apply_windows_app_id() -> None:
    """Give this process its own AppUserModelID so the taskbar shows the JARVIS
    icon (not the python.exe icon) and groups the window on its own."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("JARVIS.MarkL.1")
    except Exception as e:
        print(f"[UI] ⚠️ AppUserModelID failed: {e}")


def _find_splash_music() -> str:
    """Locate the splash music file (e.g. AC/DC — Back in Black), or ''."""
    exts = (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac")
    names = (
        "back_in_black", "back in black", "Back In Black", "Back_In_Black",
        "backinblack", "BackInBlack",
    )
    search_dirs = [
        BASE_DIR / "music",
        BASE_DIR,
        Path.home() / "Music",
        Path.home() / "Downloads",
        Path.home() / "Desktop",
    ]
    for d in search_dirs:
        if not d.is_dir():
            continue
        for name in names:
            for ext in exts:
                p = d / (name + ext)
                if p.exists():
                    return str(p)
    return ""


def _pick_output_device_index() -> int | None:
    """Index of a physical output device (skip SteelSeries Sonar virtual channels)."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
    except Exception:
        return None
    _skip = ("virtual", "sonar", "microphone", "mic", "chat", "stream",
             "spdif", "digital", "переназначение")

    def _physical(d):
        if d["max_output_channels"] <= 0:
            return False
        name = (d["name"] or "").lower()
        if any(b in name for b in _skip):
            return False
        return any(k in name for k in ("динамики", "speaker", "наушники", "headphone"))

    candidates = [i for i, d in enumerate(devices) if _physical(d)]
    if not candidates:
        candidates = [i for i, d in enumerate(devices)
                      if d["max_output_channels"] > 0
                      and not any(b in (d["name"] or "").lower() for b in _skip)]
    if not candidates:
        return None
    # Prefer WASAPI (cleanest Windows output), otherwise the first match.
    for i in candidates:
        h = int(devices[i].get("hostapi") or 0)
        if h < len(hostapis) and "wasapi" in (hostapis[h]["name"] or "").lower():
            return i
    return candidates[0]


def _decode_splash_music(path: str, seconds: float = 8.0, sample_rate: int = 44100,
                         volume: float = 1.0):
    """Decode the first `seconds` of the music to float32 PCM via ffmpeg.

    Returns (audio, sample_rate) or (None, None). This keeps the heavy decode
    OUT of the Qt Multimedia backend — we only feed PCM to sounddevice.
    """
    try:
        import subprocess
        import numpy as np
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        print(f"[UI] music decode unavailable: {e}")
        return None, None
    sample_rate = int(sample_rate) or 44100
    cmd = [
        ffmpeg, "-y", "-i", path, "-t", f"{seconds:.1f}",
        "-f", "s16le", "-acodec", "pcm_s16le",
        "-ar", str(sample_rate), "-ac", "2", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
    except Exception as e:
        print(f"[UI] music decode failed: {e}")
        return None, None
    if proc.returncode != 0 or not proc.stdout:
        return None, None
    raw = np.frombuffer(proc.stdout, dtype=np.int16)
    if raw.size == 0:
        return None, None
    audio = raw.reshape(-1, 2).astype(np.float32) / 32768.0
    if volume != 1.0:
        audio *= float(volume)
    return audio, sample_rate


def _apply_fade_out(audio, sample_rate: int, fade_seconds: float) -> None:
    """Linearly fade out the last `fade_seconds` of the audio in-place."""
    try:
        import numpy as np
    except Exception:
        return
    n = int(sample_rate * fade_seconds)
    if n <= 0 or n >= len(audio):
        return
    ramp = np.linspace(1.0, 0.0, n, dtype=np.float32)[:, None]
    audio[-n:] = audio[-n:] * ramp


def _wait_ui(seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.02)


def _fade_opacity(effect, start: float, stop: float, seconds: float) -> None:
    steps = max(1, int(seconds / 0.02))
    for i in range(1, steps + 1):
        effect.setOpacity(start + (stop - start) * (i / steps))
        QApplication.processEvents()
        time.sleep(0.02)


def _load_splash_music(photo_seconds: float):
    """Decode the splash music (photo duration + fade tail) into PCM up-front.

    Returns (audio, rate, device) or (None, None, None).
    """
    music_path = _find_splash_music()
    if not music_path:
        return None, None, None
    device = _pick_output_device_index()
    sample_rate = 44100
    if device is not None:
        try:
            import sounddevice as sd
            sr = sd.query_devices()[device].get("default_samplerate")
            if sr:
                sample_rate = int(float(sr))
        except Exception:
            pass
    _music_tail = 5.0
    audio, rate = _decode_splash_music(
        music_path, seconds=photo_seconds + _music_tail,
        sample_rate=sample_rate, volume=0.4,
    )
    if audio is None:
        return None, None, None
    _apply_fade_out(audio, rate, _music_tail)
    return audio, rate, device


def _show_startup_splash(image_path: str, seconds: float = 7.0, music=None) -> None:
    """Show the startup photo fullscreen with fade-in/out; music fades into JARVIS.

    ``music`` is the pre-loaded (audio, rate, device) tuple from
    _load_splash_music, so the photo can cross-fade into an already-shown main
    window with no blank gap in between.
    """
    if not image_path or not Path(image_path).exists():
        return

    audio, rate, device = music if music else (None, None, None)

    try:
        from PyQt6.QtWidgets import QGraphicsOpacityEffect
        import sounddevice as sd

        pm = QPixmap(image_path)
        if pm.isNull():
            return

        # Start music (non-blocking) — sounddevice plays on its own thread,
        # so it can't deadlock the fade loop the way Qt Multimedia/FFmpeg did.
        if audio is not None and rate is not None:
            try:
                sd.play(audio, rate, device=device)
            except Exception as e:
                print(f"[UI] music play failed: {e}")
                audio = None

        splash = QLabel()
        splash.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SplashScreen
        )
        splash.setStyleSheet("background: black;")
        splash.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scr = QApplication.primaryScreen().availableGeometry()
        splash.setPixmap(pm.scaled(
            scr.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

        effect = QGraphicsOpacityEffect(splash)
        splash.setGraphicsEffect(effect)
        effect.setOpacity(0.0)

        splash.showFullScreen()

        fade_in, fade_out = 1.5, 1.5
        hold = max(0.0, seconds - fade_in - fade_out)
        _fade_opacity(effect, 0.0, 1.0, fade_in)
        if hold > 0:
            _wait_ui(hold)
        _fade_opacity(effect, 1.0, 0.0, fade_out)

        splash.close()
        # Music continues on its own — the decoded tail fades out over ~5s
        # while JARVIS is already visible underneath.
    except Exception as e:
        print(f"[UI] startup splash failed: {e}")
        if audio is not None:
            try:
                import sounddevice as sd
                sd.stop()
            except Exception:
                pass


class JarvisUI:
    def __init__(self, face_path: str, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")

        # JARVIS taskbar/app icon — applied before the window is shown so
        # Windows uses it instead of the default python.exe icon.
        _apply_windows_app_id()
        ico = CONFIG_DIR / "jarvis.ico"
        if not ico.exists():
            try:
                MainWindow._build_jarvis_icon(ico)
            except Exception as e:
                print(f"[UI] ⚠️ icon generation failed: {e}")
        if ico.exists():
            self._app.setWindowIcon(QIcon(str(ico)))

        # Load music + build + show the main window BEFORE the splash, so the
        # photo cross-fades straight into JARVIS with no blank gap in between.
        music = _load_splash_music(photo_seconds=7.0)

        self._win = MainWindow(face_path)
        self._win.showFullScreen()

        _splash = BASE_DIR / "splash.png"
        if not _splash.exists():
            _splash = BASE_DIR / "face.png"
        _show_startup_splash(str(_splash) if _splash.exists() else "", seconds=7.0, music=music)

        self.root = _RootShim(self._app)

        # Global F4 hotkey — mute/unmute the mic from any app, even unfocused.
        self._hotkey_filter = _GlobalHotkeyFilter(self._win._toggle_mute)
        self._app.installNativeEventFilter(self._hotkey_filter)
        if not self._hotkey_filter.register():
            print("[UI] ⚠️ F4 hotkey not registered (already in use by another app?)")
        self._app.aboutToQuit.connect(self._hotkey_filter.unregister)

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def voice_volume(self) -> float:
        return self._win._voice_volume

    @property
    def current_file(self) -> str | None:
        return self._win._drop_zone.current_file()

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    @property
    def on_remote_clicked(self):
        return self._win.on_remote_clicked

    @on_remote_clicked.setter
    def on_remote_clicked(self, cb):
        self._win.on_remote_clicked = cb

    @property
    def on_interrupt(self):
        return self._win.on_interrupt

    @on_interrupt.setter
    def on_interrupt(self, cb):
        self._win.on_interrupt = cb

    def notify_phone_connected(self) -> None:
        self._win.notify_phone_connected()

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def show_content(self, title: str, text: str):
        self._win._content_sig.emit(title[:48], text[:4000])

    def prompt_reconfig(self):
        self._win._ready = False
        self._win._reconfig_sig.emit()

    def show_camera_frame(self, img_bytes: bytes):
        self._win._camera_sig.emit(img_bytes)

    def start_camera_stream(self) -> None:
        self._win.start_camera_stream()

    def stop_camera_stream(self) -> None:
        self._win.stop_camera_stream()

    @property
    def assistant_name(self) -> str:
        return self._win._assistant_name

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")
