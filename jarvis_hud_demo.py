# -*- coding: utf-8 -*-
"""
JARVIS HUD — standalone visual demo.

Извлечённый дизайн интерфейса MARK L (верх/низ/боковые HUD-панели + JARVIS
в центре), БЕЗ голосового движка, тулзов и API-ключей.

Запуск:
    python jarvis_hud_demo.py

Зависимости:
    PyQt6            (обязательно)
    pillow           (опционально — если рядом лежит face.png)

Горячие клавиши для просмотра состояний:
    Space — показать/скрыть режим "SPEAKING"
    M     — включить/выключить mute
"""

from __future__ import annotations

import math
import random
import time
from pathlib import Path

from PyQt6.QtCore import (
    QPointF, QRectF, Qt, QTimer,
)
from PyQt6.QtGui import (
    QBrush, QColor, QConicalGradient, QFont, QPainter, QPainterPath,
    QPen, QPixmap, QRadialGradient,
)
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QPushButton, QSizePolicy, QSlider, QTextEdit, QVBoxLayout, QWidget,
)


# ── Цветовая палитра (как в ui.py) ────────────────────────────────────────────
class C:
    BG        = "#00060a"
    PANEL     = "#010d14"
    PANEL2    = "#010f18"
    BORDER    = "#0d3347"
    BORDER_B  = "#1a5c7a"
    BORDER_A  = "#0f4060"
    PRI       = "#00d4ff"
    PRI_DIM   = "#007a99"
    PRI_GHO   = "#001f2e"
    ACC       = "#ff6b00"
    ACC2      = "#ffcc00"
    GREEN     = "#00ff88"
    GREEN_D   = "#00aa55"
    RED       = "#ff3355"
    MUTED_C   = "#ff3366"
    TEXT      = "#8ffcff"
    TEXT_DIM  = "#3a8a9a"
    TEXT_MED  = "#5ab8cc"
    WHITE     = "#d8f8ff"
    DARK      = "#000d14"
    BAR_BG    = "#011520"


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h)
    c.setAlpha(a)
    return c


# ── Метрика-бар (левая панель) ────────────────────────────────────────────────
class MetricBar(QWidget):
    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0
        self._text  = "--"
        self.setFixedHeight(20)
        self.setMinimumWidth(80)

    def set_value(self, pct: float, text: str):
        self._value = max(0.0, min(100.0, pct))
        self._text  = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        label_w, val_w = 34, 44
        bar_x = label_w + 4
        bar_w = max(10, W - label_w - val_w - 8)
        bar_y = H / 2 - 1
        bar_h = 2

        p.setFont(QFont("Segoe UI", 6))
        p.setPen(QPen(qcol(C.TEXT_DIM, 190), 1))
        p.drawText(QRectF(0, 0, label_w, H),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._label)

        if self._value > 85:
            col = C.RED
        elif self._value > 65:
            col = C.ACC
        else:
            col = self._color

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(C.BAR_BG, 130)))
        p.drawRect(QRectF(bar_x, bar_y, bar_w, bar_h))
        fill_w = int(bar_w * self._value / 100.0)
        if fill_w > 0:
            p.setBrush(QBrush(qcol(col, 210)))
            p.drawRect(QRectF(bar_x, bar_y, fill_w, bar_h))

        p.setFont(QFont("Segoe UI", 7))
        p.setPen(QPen(qcol(col if self._text != "--" else C.TEXT_DIM, 220), 1))
        p.drawText(QRectF(bar_x + bar_w + 4, 0, val_w, H),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   self._text)


# ── Лог-панель (правая панель) ────────────────────────────────────────────────
class LogWidget(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setStyleSheet(f"""
            QTextEdit {{
                background: {C.PANEL}; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px;
                padding: 5px; font-family: "Courier New"; font-size: 8pt;
            }}
        """)
        self.setMinimumHeight(120)

    def append_log(self, text: str):
        self.append(text)


# ── Центральный JARVIS (HUD-канвас) ───────────────────────────────────────────
class HudCanvas(QWidget):
    def __init__(self, face_path: str = "", assistant_name: str = "J.A.R.V.I.S",
                 parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted    = False
        self.speaking = False
        self.state    = "LISTENING"
        self._assistant_name = assistant_name

        self._t          = 0.0
        self._last_t     = time.time()
        self._breathe    = 0.0
        self._rot_slow   = 0.0
        self._rot_mid    = 0.0
        self._rot_fast   = 0.0
        self._orbit      = 0.0
        self._scan       = 0.0
        self._glow       = 40.0
        self._tgt_glow   = 40.0
        self._pulse      = 0.0
        self._wave       = [0.0] * 64
        self._blink      = True
        self._blink_tick = 0
        self._particles: list[list[float]] = []
        self._face_px: QPixmap | None = None
        self._data_lbls = ["SYS", "CORE", "PWR", "NET", "MEM", "AI"]

        self._pings: list[list[float]] = []
        self._ping_acc    = 0.0
        self._bars        = [0.0] * 48
        self._burst       = 0.0
        self._prev_speak  = False

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

    def _activity(self) -> float:
        if self.speaking:
            return 1.0
        if self.state in ("THINKING", "PROCESSING"):
            return 0.6
        if self.state == "LISTENING":
            return 0.45
        if self.muted:
            return 0.04
        return 0.15

    def _acc(self) -> str:
        if self.muted:
            return C.MUTED_C
        if self.speaking:
            return C.PRI
        if self.state in ("THINKING", "PROCESSING"):
            return C.ACC2
        return C.PRI

    def _step(self):
        now = time.time()
        dt  = max(0.0, min(0.05, now - self._last_t))
        self._last_t = now
        self._t      += dt
        act = self._activity()

        if self.speaking and not self._prev_speak:
            self._burst = 1.0
        self._prev_speak = self.speaking
        self._burst = max(0.0, self._burst - dt * 2.0)

        self._breathe  += dt
        self._rot_slow += dt * (0.10 + 0.20 * act)
        self._rot_mid  += dt * (0.25 + 0.45 * act)
        self._rot_fast += dt * (0.55 + 0.90 * act)
        self._orbit    += dt * (0.30 + 0.70 * act)
        self._scan      = (self._scan + dt * (0.20 + 0.50 * act)) % 1.0

        if self.speaking:
            tgt = 95.0 + 20.0 * math.sin(self._t * 9.0)
        elif self.state in ("THINKING", "PROCESSING"):
            tgt = 70.0 + 8.0 * math.sin(self._t * 5.0)
        elif self.state == "LISTENING":
            tgt = 56.0 + 4.0 * math.sin(self._t * 1.8)
        elif self.muted:
            tgt = 12.0
        else:
            tgt = 40.0 + 4.0 * math.sin(self._t * 1.6)
        self._glow += (tgt - self._glow) * (1.0 - math.exp(-dt * 6.0))

        self._pulse += dt * (0.35 if self.speaking else 0.10)
        if self._pulse > 1.0:
            self._pulse = 0.0

        if self.speaking:
            amp = 0.5 + 0.45 * self._burst
        elif self.state == "LISTENING":
            amp = 0.18
        else:
            amp = 0.05
        if self.muted:
            amp = 0.0
        for i in range(len(self._wave)):
            ph = self._t * (4.0 + 3.0 * act) + i * 0.5
            self._wave[i] = (math.sin(ph) * 0.6 + math.sin(ph * 2.13) * 0.4) * amp

        if self.state == "LISTENING" and not self.muted:
            self._ping_acc += dt
            if self._ping_acc >= 1.1:
                self._ping_acc = 0.0
                self._pings.append([0.16, 1.0])
        else:
            self._ping_acc = 0.0
        kept_pings: list[list[float]] = []
        for pr, pa in self._pings:
            pr += dt * 0.38
            pa -= dt * 0.6
            if pr < 0.72 and pa > 0.0:
                kept_pings.append([pr, pa])
        self._pings = kept_pings

        bar_amp = 0.9 if self.speaking else (0.30 if self.state == "LISTENING" else 0.12)
        if self.muted:
            bar_amp = 0.0
        for i in range(len(self._bars)):
            ph = self._t * (6.0 + 4.0 * act) + i * 0.55
            nz = (math.sin(ph) * 0.55 + math.sin(ph * 2.7 + i) * 0.30
                  + math.sin(ph * 5.1) * 0.15)
            nz += random.uniform(-0.18, 0.18)
            target = max(0.0, min(1.0, nz)) * bar_amp
            self._bars[i] += (target - self._bars[i]) * (1.0 - math.exp(-dt * 14.0))

        cx, cy = self.width() / 2, self.height() / 2
        fw = min(self.width(), self.height())
        if random.random() < (0.02 + 0.10 * act):
            ang = random.uniform(0, 2 * math.pi)
            r   = fw * random.uniform(0.35, 0.75)
            inward = self.speaking or self.state == "LISTENING"
            spd = 2.0 + 6.0 * act
            self._particles.append([
                cx + math.cos(ang) * r,
                cy + math.sin(ang) * r,
                math.cos(ang) * spd * (1.0 if inward else -0.25),
                math.sin(ang) * spd * (1.0 if inward else -0.25),
                random.uniform(0.4, 1.0),
                random.choice([0.3, 0.6, 1.0]),
                random.uniform(1.0, 2.2),
            ])
        pull = 1.0 if (self.speaking or self.state == "LISTENING") else 0.0
        kept: list[list[float]] = []
        for pt in self._particles:
            x, y, vx, vy, life, dep, sz = pt
            if pull > 0:
                vx += (cx - x) * 0.0012 * pull
                vy += (cy - y) * 0.0012 * pull
            x += vx * dt * 7.0
            y += vy * dt * 7.0
            life -= dt * 0.35
            if life > 0 and -20 <= x <= self.width() + 20 and -20 <= y <= self.height() + 20:
                kept.append([x, y, vx, vy, life, dep, sz])
        self._particles = kept

        self._blink_tick += 1
        if self._blink_tick >= 40:
            self._blink = not self._blink
            self._blink_tick = 0
        self.update()

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

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)
        act  = self._activity()
        glow = self._glow

        # 1) фон
        bg = QRadialGradient(cx, cy, fw * 0.9)
        bg.setColorAt(0.0, QColor("#04121a"))
        bg.setColorAt(0.55, QColor("#020a10"))
        bg.setColorAt(1.0, QColor("#010507"))
        p.fillRect(self.rect(), QBrush(bg))

        # 2) еле заметная сетка
        step = max(48, fw // 12)
        p.setPen(QPen(QColor(0, 60, 85, 26), 1))
        for x in range(int(cx % step), W, step):
            p.drawLine(x, 0, x, H)
        for y in range(int(cy % step), H, step):
            p.drawLine(0, y, W, y)

        # 3) крупные геометрические структуры
        p.setPen(QPen(qcol(C.PRI, int(8 + 16 * act)), 1))
        for rf, rot, verts in ((0.62, self._rot_slow, 6), (0.50, -self._rot_mid, 8)):
            pts = []
            for v in range(verts):
                a = rot + v * (2 * math.pi / verts)
                r = fw * rf
                pts.append(QPointF(cx + math.cos(a) * r, cy + math.sin(a) * r))
            path = QPainterPath()
            path.moveTo(pts[0])
            for pt in pts[1:]:
                path.lineTo(pt)
            path.closeSubpath()
            p.drawPath(path)

        # 4) орбитальные кольца
        for rf, th, arc_len, rot in (
            (0.56, 0.55, 60, self._rot_mid),
            (0.47, 0.42, 80, -self._rot_fast),
            (0.38, 0.30, 120, self._rot_slow),
        ):
            r = fw * rf
            a = int(22 + 50 * act + glow * 0.25)
            p.setPen(QPen(qcol(C.PRI, min(255, a)), th))
            rect = QRectF(cx - r, cy - r, r * 2, r * 2)
            ang = int(rot * 360)
            p.drawArc(rect, int(ang * 16), int(arc_len * 16))
            p.drawArc(rect, int((ang + 180) * 16), int((arc_len * 0.6) * 16))

        # 5) засечки на внешнем кольце
        t_out, t_in = fw * 0.56, fw * 0.535
        p.setPen(QPen(qcol(C.PRI, 55), 1))
        for deg in range(0, 360, 12):
            rad = math.radians(deg + self._rot_slow * 20)
            p.drawLine(QPointF(cx + t_out * math.cos(rad), cy + t_out * math.sin(rad)),
                       QPointF(cx + t_in  * math.cos(rad), cy + t_in  * math.sin(rad)))

        # 6) орбитальные узлы с линиями к центру
        for k in range(3):
            a = self._orbit + k * (2 * math.pi / 3)
            r = fw * 0.42
            nx, ny = cx + math.cos(a) * r, cy + math.sin(a) * r
            p.setPen(QPen(qcol(C.PRI, int(18 + 36 * act)), 1))
            p.drawLine(QPointF(nx, ny), QPointF(cx, cy))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.ACC if self.speaking else C.PRI, 200)))
            p.drawEllipse(QPointF(nx, ny), 2.2, 2.2)

        # 7) ядро — многослойное свечение
        core_r = fw * (0.16 + 0.012 * math.sin(self._breathe * 1.4))
        for i in range(6):
            frc = 1.0 - i / 6
            r = core_r * (2.4 - i * 0.22)
            a = int(glow * 0.9 * frc)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(self._acc(), max(0, min(255, a)))))
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        p.setPen(QPen(qcol(C.WHITE, min(255, int(glow * 1.4))), 1.3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(cx - core_r, cy - core_r, core_r * 2, core_r * 2))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(C.WHITE, min(255, int(glow * 1.6)))))
        p.drawEllipse(QPointF(cx, cy), core_r * 0.30, core_r * 0.30)

        # 8) лицо (если есть face.png) — едва заметно позади ядра
        if self._face_px:
            fsz = int(fw * 0.30)
            scaled = self._face_px.scaled(
                fsz, fsz,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.setOpacity(0.15)
            p.drawPixmap(int(cx - fsz / 2), int(cy - fsz / 2), scaled)
            p.setOpacity(1.0)

        # 9) радиальный пульс
        if self.speaking or self.state == "LISTENING":
            base = 0.16 + (0.10 * self._burst if self.speaking else 0.0)
            pr = fw * (base + self._pulse * 0.46)
            al = (120 + 70 * self._burst if self.speaking else 110) * (1.0 - self._pulse)
            p.setPen(QPen(qcol(self._acc(), int(max(0.0, al))), 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - pr, cy - pr, pr * 2, pr * 2))

        # 10) частицы
        for pt in self._particles:
            x, y, _vx, _vy, life, dep, sz = pt
            a = int(255 * life * (0.25 + 0.55 * dep))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(self._acc(), a)))
            p.drawEllipse(QPointF(x, y), sz * dep, sz * dep)

        # 11) вращающиеся метки
        p.setFont(QFont("Segoe UI", 7))
        for i, lbl in enumerate(self._data_lbls):
            a = self._rot_fast * 0.6 + i * (2 * math.pi / len(self._data_lbls))
            r = fw * 0.60
            tx = cx + math.cos(a) * r
            ty = cy + math.sin(a) * r
            p.setPen(QPen(qcol(C.PRI, 90), 1))
            p.drawText(QRectF(tx - 22, ty - 8, 44, 16), Qt.AlignmentFlag.AlignCenter, lbl)

        # 12) круговая волна вокруг ядра
        wv_r = fw * 0.30
        n = len(self._wave)
        path = QPainterPath()
        for i in range(n + 1):
            idx = i % n
            a = (i / n) * 2 * math.pi - math.pi / 2
            r = wv_r * (1.0 + self._wave[idx] * 0.5)
            x = cx + math.cos(a) * r
            y = cy + math.sin(a) * r
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        p.setPen(QPen(qcol(self._acc(), min(255, int(110 + glow))), 1.3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # 12b) сонар-кольца (listening)
        for pr, pa in self._pings:
            r = fw * pr
            p.setPen(QPen(qcol(self._acc(), int(120 * pa)), 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # 12c) радиальные EQ-бары (speaking)
        if self.speaking:
            n_bars = len(self._bars)
            inner = fw * 0.40
            for i in range(n_bars):
                amp = self._bars[i]
                if amp < 0.03:
                    continue
                a = (i / n_bars) * 2 * math.pi
                ca, sa = math.cos(a), math.sin(a)
                r1 = inner + fw * (0.08 + 0.26 * amp)
                al = int(70 + 160 * amp)
                p.setPen(QPen(qcol(self._acc(), al), max(1.0, 1.2 + 2.2 * amp)))
                p.drawLine(QPointF(cx + ca * inner, cy + sa * inner),
                           QPointF(cx + ca * r1, cy + sa * r1))

        # 12d) радар-развёртка
        sweep_deg = self._scan * 360.0
        cg = QConicalGradient(cx, cy, sweep_deg - 90.0)
        cg.setColorAt(0.0, qcol(self._acc(), int(20 + 55 * act)))
        cg.setColorAt(0.07, qcol(self._acc(), 0))
        cg.setColorAt(1.0, qcol(self._acc(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(cg))
        p.drawPie(QRectF(cx - fw * 0.5, cy - fw * 0.5, fw, fw), 0, 360 * 16)

        # 13) статус-надпись
        txt, col = self._status_label()
        sym = "●" if (self._blink or self.speaking) else "○"
        sy = cy + fw * 0.40
        p.setPen(QPen(qcol(col, 220), 1))
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.Light))
        p.drawText(QRectF(0, sy, W, 22), Qt.AlignmentFlag.AlignCenter, f"{sym}  {txt}")

        # 14) уголки-скобки
        bl, m = 16, 6
        p.setPen(QPen(qcol(C.PRI, 70), 1))
        for bx, by, dx, dy in ((m, m, 1, 1), (W - m, m, -1, 1),
                               (m, H - m, 1, -1), (W - m, H - m, -1, -1)):
            p.drawLine(QPointF(bx, by), QPointF(bx + dx * bl, by))
            p.drawLine(QPointF(bx, by), QPointF(bx, by + dy * bl))


# ── Главное окно (собирает HUD: верх/низ/бока + центр) ────────────────────────
class MainWindow(QMainWindow):
    def __init__(self, face_path: str = ""):
        super().__init__()
        self.setWindowTitle("JARVIS — MARK XLIX")
        self.resize(980, 700)
        self.setMinimumSize(820, 580)

        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_left_panel(), stretch=0)

        self.hud = HudCanvas(face_path, "JARVIS")
        self.hud.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        body.addWidget(self.hud, stretch=5)

        body.addWidget(self._build_right_panel(), stretch=0)
        root.addLayout(body, stretch=1)
        root.addWidget(self._build_footer())

        # часы
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y"))
        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)

        # фейковые метрики, чтобы дизайн "дышал"
        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)
        self._update_metrics()

        # демо-лог
        self._log.append_log("SYS: JARVIS online.")
        self._log.append_log("SYS: Дизайн-демо (без голосового движка).")

    # ── верх ─────────────────────────────────────────────────────────────────
    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(54)
        w.setStyleSheet(f"background: {C.DARK}; border-bottom: 1px solid {C.BORDER_B};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 0, 16, 0)

        badge = QLabel("MARK XLIX")
        badge.setFont(QFont("Courier New", 8))
        badge.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        lay.addWidget(badge)
        lay.addStretch()

        mid = QVBoxLayout()
        mid.setSpacing(1)
        title = QLabel("JARVIS")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Segoe UI", 19, QFont.Weight.Light))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        mid.addWidget(title)
        sub = QLabel("Just A Rather Very Intelligent System")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setFont(QFont("Segoe UI", 7))
        sub.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        mid.addWidget(sub)
        lay.addLayout(mid)
        lay.addStretch()

        right_col = QVBoxLayout()
        right_col.setSpacing(2)
        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Light))
        self._clock_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._clock_lbl)
        self._date_lbl = QLabel("")
        self._date_lbl.setFont(QFont("Courier New", 7))
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._date_lbl)
        self._status_lbl = QLabel("●  STANDBY")
        self._status_lbl.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        self._status_lbl.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._status_lbl)
        lay.addLayout(right_col)
        return w

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y"))

    # ── левая панель ──────────────────────────────────────────────────────────
    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(148)
        w.setStyleSheet(f"background: rgba(2, 8, 14, 235); border-right: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 14, 10, 10)
        lay.setSpacing(8)

        hdr = QLabel("SYSTEM")
        hdr.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent; "
                          f"border-bottom: 1px solid {C.BORDER}; padding-bottom: 5px;")
        lay.addWidget(hdr)

        self._bar_cpu = MetricBar("CPU", C.PRI)
        self._bar_mem = MetricBar("MEM", C.PRI_DIM)
        self._bar_net = MetricBar("NET", C.TEXT_MED)
        self._bar_gpu = MetricBar("GPU", C.PRI_DIM)
        self._bar_tmp = MetricBar("TMP", C.TEXT_MED)
        for bar in [self._bar_cpu, self._bar_mem, self._bar_net,
                    self._bar_gpu, self._bar_tmp]:
            lay.addWidget(bar)

        lay.addSpacing(2)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};")
        lay.addWidget(sep)

        up = QLabel("UP  --:--")
        up.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        up.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        lay.addWidget(up)

        proc = QLabel("PROC  --")
        proc.setFont(QFont("Segoe UI", 7))
        proc.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        lay.addWidget(proc)

        osl = QLabel("OS  WIN")
        osl.setFont(QFont("Segoe UI", 7))
        osl.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        lay.addWidget(osl)

        lay.addStretch()
        foot = QLabel("AI CORE · ACTIVE")
        foot.setFont(QFont("Segoe UI", 6, QFont.Weight.Bold))
        foot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        foot.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        lay.addWidget(foot)
        return w

    def _update_metrics(self):
        import psutil  # опционально; если нет — значения фейковые
        def _pct(base, amp):
            v = base + amp * math.sin(time.time() * 0.7 + base)
            return max(0, min(100, v))

        try:
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
        except Exception:
            cpu = _pct(35, 25)
            mem = _pct(50, 15)
        net = _pct(20, 12)
        gpu = _pct(40, 18)
        tmp = _pct(52, 6)

        self._bar_cpu.set_value(cpu, f"{int(cpu)}%")
        self._bar_mem.set_value(mem, f"{int(mem)}%")
        self._bar_net.set_value(net, f"{int(net)}%")
        self._bar_gpu.set_value(gpu, f"{int(gpu)}%")
        self._bar_tmp.set_value(tmp, f"{int(tmp)}°")

    # ── правая панель ─────────────────────────────────────────────────────────
    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(340)
        w.setStyleSheet(f"background: {C.DARK}; border-left: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        def _sec(txt):
            l = QLabel(f"▸ {txt}")
            l.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
            l.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
            return l

        lay.addWidget(_sec("ACTIVITY LOG"))
        self._log = LogWidget()
        lay.addWidget(self._log, stretch=1)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        lay.addWidget(_sec("FILE UPLOAD"))
        drop = QLabel("⬆  Drop file here")
        drop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop.setFixedHeight(40)
        drop.setStyleSheet(f"""
            color: {C.TEXT_MED}; background: {C.PANEL};
            border: 1px dashed {C.BORDER}; border-radius: 3px;
        """)
        lay.addWidget(drop)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_sec("COMMAND INPUT"))
        row = QHBoxLayout()
        row.setSpacing(5)
        inp = QLineEdit()
        inp.setPlaceholderText("Speak or enter a command…")
        inp.setFont(QFont("Segoe UI", 9))
        inp.setFixedHeight(30)
        inp.setStyleSheet(f"""
            QLineEdit {{
                background: #000d14; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 3px 7px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        row.addWidget(inp)
        send = QPushButton("▸")
        send.setFixedSize(30, 30)
        send.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        row.addWidget(send)
        lay.addLayout(row)

        intr = QPushButton("✋  INTERRUPT  [ESC]")
        intr.setFixedHeight(34)
        intr.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        intr.setCursor(Qt.CursorShape.PointingHandCursor)
        intr.setStyleSheet(f"""
            QPushButton {{
                background: #140008; color: {C.MUTED_C};
                border: 1px solid {C.MUTED_C}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: #200010; border: 1px solid #ff6688; }}
            QPushButton:pressed {{ background: #300018; }}
        """)
        lay.addWidget(intr)

        self._mute_btn = QPushButton("🎙  MICROPHONE ACTIVE")
        self._mute_btn.setFixedHeight(30)
        self._mute_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()
        lay.addWidget(self._mute_btn)

        lay.addWidget(_sec("VOICE VOLUME"))
        voll = QLabel("🔊  100%")
        voll.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        voll.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(voll)
        vol = QSlider(Qt.Orientation.Horizontal)
        vol.setRange(0, 100)
        vol.setValue(100)
        vol.setFixedHeight(18)
        vol.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 4px; background: {C.BAR_BG};
                border: 1px solid {C.BORDER}; border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{
                background: {C.PRI_DIM}; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                width: 14px; margin: -5px 0;
                background: {C.PRI}; border-radius: 7px;
                border: 1px solid {C.BORDER_B};
            }}
        """)
        lay.addWidget(vol)
        return w

    def _toggle_mute(self):
        self.hud.muted = not self.hud.muted
        self._style_mute_btn()
        self._log.append_log("SYS: Microphone muted." if self.hud.muted
                             else "SYS: Microphone active.")

    def _style_mute_btn(self):
        if self.hud.muted:
            self._mute_btn.setText("🔇  MICROPHONE MUTED")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #140006; color: {C.MUTED_C};
                    border: 1px solid {C.MUTED_C}; border-radius: 3px;
                }}
            """)
        else:
            self._mute_btn.setText("🎙  MICROPHONE ACTIVE")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #00140a; color: {C.GREEN};
                    border: 1px solid {C.GREEN}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #001f10; }}
            """)

    # ── низ ──────────────────────────────────────────────────────────────────
    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(22)
        w.setStyleSheet(f"background: {C.DARK}; border-top: 1px solid {C.BORDER};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(14, 0, 14, 0)

        l1 = QLabel("[Space] Speak  ·  [M] Mute")
        l1.setFont(QFont("Courier New", 7))
        l1.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        lay.addWidget(l1)
        lay.addStretch()
        l2 = QLabel("JARVIS · HUD demo")
        l2.setFont(QFont("Courier New", 7))
        l2.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        lay.addWidget(l2)
        return w

    # ── горячие клавиши для просмотра состояний ──────────────────────────────
    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Space:
            self.hud.speaking = not self.hud.speaking
            if not self.hud.speaking:
                self.hud.state = "LISTENING"
        elif e.key() == Qt.Key.Key_M:
            self._toggle_mute()
        else:
            super().keyPressEvent(e)


def main():
    app = QApplication([])
    app.setStyle("Fusion")

    # Если рядом лежит face.png — подхватится автоматически
    face = Path(__file__).parent / "face.png"
    face_path = str(face) if face.exists() else ""

    win = MainWindow(face_path)
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
