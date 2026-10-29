"""Home page: one clear way in for new users, with the other entry points one step to the side.

Layout (top to bottom):
* a one-line introduction and the three-step workflow (choose → build & check → run & explore), which
  matches the Model / Simulate / Results pages in the navigation rail;
* the validated cases as a compact list – the recommended starting point;
* a side column with the other ways to start (guided setup, open a saved model, recent models) and the
  learning material (1-minute demo, quick start, tutorial).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)

from .. import advisor as A
from .. import solver as S
from ..model import StudioModel
from ..units import human_duration
from . import icons
from . import theme as T
from .widgets import ElidedLabel, hline, label, push

CASE_ICONS = {
    "config_case_nitrogen_pulsed_discharge": ("bolt", "#7c3aed"),
    "config_case_argon_dc_discharge": ("wave", "#2563eb"),
    "config_case_argon_photoemission_discharge": ("emission", "#db2777"),
    "config_case_deuterium_pulsed_discharge": ("atom", "#0891b2"),
    "config_case_helium_photoemission_discharge": ("gas", "#ea580c"),
    "config": ("book", "#64748b"),
}
RECOMMENDED = "config_case_nitrogen_pulsed_discharge"     # the paper benchmark and the 1-minute demo
STEPS = ["Choose a starting point – a validated case, the guided setup or a saved model",
         "Set up and check the model", "Run it and explore the results"]


def _bubble(icon: str, col: str, size: int = 36) -> QLabel:
    b = QLabel()
    b.setFixedSize(size, size)
    b.setAlignment(Qt.AlignCenter)
    qc = QColor(col)
    b.setStyleSheet(f"background: rgba({qc.red()},{qc.green()},{qc.blue()},0.13); border-radius: {size // 4}px;")
    b.setPixmap(icons.pixmap(icon, col, int(size * 0.55)))
    return b


class _Title(ElidedLabel):
    """Bold case name: as wide as its text when there is room, shortened with … when there is not."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

    def sizeHint(self):  # noqa: N802
        sh = super().sizeHint()
        return QSize(self.fontMetrics().horizontalAdvance(self.full_text()) + 4, sh.height())


class CaseRow(QFrame):
    """One validated case: name, one-line summary, run-time estimate, Open (and a low-key Demo)."""

    def __init__(self, info, on_open, on_demo, parent=None):
        super().__init__(parent)
        self.setObjectName("rowCard")
        self.setCursor(Qt.PointingHandCursor)
        self.info = info
        self.on_open = on_open
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(12)
        ic, col = CASE_ICONS.get(info.module, ("model", "#64748b"))
        h.addWidget(_bubble(ic, col), 0, Qt.AlignTop)
        tv = QVBoxLayout()
        tv.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(8)
        t = _Title(info.title, mode=Qt.ElideRight)           # long names shorten instead of being cut
        f = t.font()
        f.setBold(True)
        t.setFont(f)
        t.setMinimumWidth(60)
        top.addWidget(t)
        if info.module == RECOMMENDED:
            top.addWidget(_chip("Start here", accent=True))
        top.addStretch(1)
        tv.addLayout(top)
        s = ElidedLabel(info.summary, mode=Qt.ElideRight)
        s.setObjectName("muted")
        s.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        tv.addWidget(s)
        h.addLayout(tv, 1)
        try:
            est = human_duration(A.estimate(StudioModel(info.module))["runtime_s"])
        except Exception:
            est = ""
        self.est = label(f"≈ {est}" if est else "", "faint")
        self.est.setToolTip("Estimated run time on this computer")
        self.est.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.est.setMinimumWidth(96)
        h.addWidget(self.est)
        d = push("Demo", "ghost", icon_name="play")
        d.setToolTip("Run a short, coarse version right away to see what this case does")
        d.clicked.connect(lambda: on_demo(info.module))
        d.setMinimumWidth(96)
        d.setVisible(False)                              # secondary action: takes the run-time slot on hover
        self.demo = d
        h.addWidget(d)
        rec = info.module == RECOMMENDED                 # exactly one emphasised button on the page
        b = push("Open", "primary" if rec else None, icon_name="chevron_right")
        b.setLayoutDirection(Qt.RightToLeft)              # chevron after the word
        b.setToolTip("Open this case in the Model page to review, adjust and run it")
        b.clicked.connect(lambda: on_open(info.module))
        h.addWidget(b)
        tags = " · ".join(info.tags)
        self.setToolTip(f"<b>{info.title}</b><br>{info.summary}<br><br>"
                        f"<span style='color:gray'>{tags}<br>{info.module}.py</span>")

    def contextMenuEvent(self, e):                       # the same actions by right-click
        m = QMenu(self)
        m.addAction(icons.icon("chevron_right", T.c("text2"), 16), "Open", lambda: self.on_open(self.info.module))
        m.addAction(icons.icon("play", T.c("text2"), 16), "Quick demo", self.demo.click)
        m.exec(e.globalPos())

    def enterEvent(self, e):
        self.est.setVisible(False)
        self.demo.setVisible(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.demo.setVisible(False)
        self.est.setVisible(True)
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.on_open(self.info.module)
        super().mouseReleaseEvent(e)


class ModelPicture(QWidget):
    """What PASCHEN-1D models, in one picture: a voltage source drives a 1D gas gap between two electrodes
    through an external circuit; electrons drift to the anode, ions to the cathode."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(240, 176)
        sp = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        sp.setHeightForWidth(True)                  # the picture keeps its proportions as the column grows
        self.setSizePolicy(sp)
        self.setToolTip("PASCHEN-1D solves electron and ion drift–diffusion with Poisson's equation in the gap, "
                        "with surface emission at the electrodes and the external circuit – all coupled.")

    def sizeHint(self):  # noqa: D401
        return QSize(360, 176)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, w):  # noqa: N802
        return int(176 * max(0.67, min(w / 360.0, 1.6)))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        k = min(W / 360.0, 1.6)
        ox = (W - 360 * k) / 2
        X = lambda x: ox + x * k              # noqa: E731
        Y = lambda y: y * (H / 176.0)          # noqa: E731
        NC = Qt.TextDontClip
        fg, fg2, acc = QColor(T.c("text")), QColor(T.c("text2")), QColor(T.c("accent"))
        el, ion = QColor(T.c("role")["electron"]), QColor(T.c("role")["ion"])
        top, bot = Y(30), Y(160)
        ax, cx = X(182), X(286)                # anode / cathode electrodes (x = 0 and x = L)
        # gas gap
        g = QLinearGradient(ax, 0, cx, 0)
        g.setColorAt(0, QColor(124, 58, 237, 40))
        g.setColorAt(0.5, QColor(168, 85, 247, 75))
        g.setColorAt(1, QColor(124, 58, 237, 40))
        p.fillRect(QRectF(ax + 7 * k, Y(44), cx - ax - 7 * k, Y(88)), g)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T.c("text3")))
        for x0 in (ax, cx):
            p.drawRoundedRect(QRectF(x0, Y(40), 7 * k, Y(96)), 2, 2)
        # wiring: source → external circuit → anode;  cathode → ground → source
        sx, sy, r = X(80), (top + bot) / 2, 15 * k
        p.setPen(QPen(fg2, 1.6))
        p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(sx, sy - r), QPointF(sx, top))
        p.drawLine(QPointF(sx, top), QPointF(X(98), top))
        box = QRectF(X(98), top - 11 * k, X(158) - X(98), 22 * k)   # R, L and/or C – depends on the topology
        p.drawRoundedRect(box, 3, 3)
        p.drawLine(QPointF(X(158), top), QPointF(ax + 3.5 * k, top))
        p.drawLine(QPointF(ax + 3.5 * k, top), QPointF(ax + 3.5 * k, Y(40)))
        p.drawLine(QPointF(cx + 3.5 * k, Y(136)), QPointF(cx + 3.5 * k, bot))
        p.drawLine(QPointF(cx + 3.5 * k, bot), QPointF(sx, bot))
        p.drawLine(QPointF(sx, bot), QPointF(sx, sy + r))
        for gx in range(3):                     # ground symbol
            w = (12 - 4 * gx) * k
            p.drawLine(QPointF(X(130) - w, bot + (5 + 4 * gx) * k), QPointF(X(130) + w, bot + (5 + 4 * gx) * k))
        p.drawLine(QPointF(X(130), bot), QPointF(X(130), bot + 5 * k))
        # source V_app(t)
        p.setPen(QPen(fg, 1.6))
        p.setBrush(QColor(T.c("surface")))
        p.drawEllipse(QPointF(sx, sy), r, r)
        path = QPainterPath(QPointF(sx - r * 0.6, sy))
        path.cubicTo(QPointF(sx - r * 0.3, sy - r * 0.8), QPointF(sx, sy - r * 0.8), QPointF(sx, sy))
        path.cubicTo(QPointF(sx, sy + r * 0.8), QPointF(sx + r * 0.3, sy + r * 0.8), QPointF(sx + r * 0.6, sy))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        base = self.font()
        small = QFont(base)
        small.setPointSizeF(max(6.0, (base.pointSizeF() - 1.5) * min(1.0, k * 1.08)))   # text scales with the picture
        bold = QFont(small)
        bold.setBold(True)

        def arrow(y, x1, x2, col, text):
            p.setPen(QPen(col, 2))
            p.drawLine(QPointF(x1, y), QPointF(x2, y))
            d = 1 if x2 > x1 else -1
            p.drawLine(QPointF(x2, y), QPointF(x2 - d * 7 * k, y - 4 * k))
            p.drawLine(QPointF(x2, y), QPointF(x2 - d * 7 * k, y + 4 * k))
            p.setFont(bold)
            p.drawText(QRectF(min(x1, x2), y - Y(19), abs(x2 - x1), Y(15)), Qt.AlignCenter | NC, text)
        arrow(Y(72), cx - 8 * k, ax + 15 * k, el, "electrons")
        arrow(Y(112), ax + 15 * k, cx - 8 * k, ion, "ions")
        p.setFont(small)
        p.setPen(fg2)
        p.drawText(QRectF(X(0), sy - Y(8), sx - r - X(4), Y(16)), Qt.AlignRight | Qt.AlignVCenter | NC, "V_app(t)")
        p.drawText(QRectF(X(98), top - 11 * k - Y(16), X(158) - X(98), Y(14)), Qt.AlignCenter | NC, "external circuit")
        p.setPen(fg)
        p.drawText(box, Qt.AlignCenter | NC, "R, L, C")
        p.setPen(fg2)
        p.drawText(QRectF(ax - 56 * k, Y(124), 52 * k, Y(14)), Qt.AlignRight | NC, "anode")
        p.drawText(QRectF(cx + 13 * k, Y(124), 52 * k, Y(14)), Qt.AlignLeft | NC, "cathode")
        p.setFont(bold)
        p.setPen(acc)
        p.drawText(QRectF(ax, Y(14), cx - ax + 7 * k, Y(14)), Qt.AlignCenter | NC, "1D gas gap")
        p.end()


def _chip(text: str, accent: bool = False) -> QLabel:
    c = QLabel(text)
    c.setObjectName("chipAccent" if accent else "chip")
    return c


class HomePage(QWidget):
    newWizard = Signal()
    openModel = Signal()
    openCase = Signal(str)
    demoCase = Signal(str)
    openRecent = Signal(str)
    showHelp = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        outer.addWidget(sc)
        body = QWidget()
        sc.setWidget(body)
        v = QVBoxLayout(body)
        v.setContentsMargins(32, 24, 32, 24)
        v.setSpacing(18)

        # ---- main area: cases | picture + alternatives ---------------------------------------
        main = QHBoxLayout()
        main.setSpacing(20)
        left = QVBoxLayout()
        left.setSpacing(8)
        self.h_right = label("Start from a validated case", "h3", wrap=True)
        self.h_right.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        left.addWidget(self.h_right)
        self.case_lay = QVBoxLayout()
        self.case_lay.setSpacing(8)
        left.addLayout(self.case_lay, 1)        # rows share any extra height: both columns end level
        cases = QWidget()                       # 60 % of the width
        cases.setLayout(left)
        left.setContentsMargins(0, 0, 0, 0)
        cases.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        side = QFrame()
        side.setObjectName("card")
        side.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)   # 40 % of the width, full column height
        sv = QVBoxLayout(side)
        sv.setContentsMargins(16, 14, 16, 14)
        sv.setSpacing(6)
        sv.addWidget(ModelPicture())
        sv.addWidget(label("Electron and ion transport, the electric field, electrode emission and the external "
                           "circuit, solved together.", "hint", wrap=True))
        sv.addSpacing(8)
        # the workflow, in three steps (it matches the Model, Simulate and Results pages)
        for i, title in enumerate(STEPS, 1):
            r = QHBoxLayout()
            r.setSpacing(10)
            n = QLabel(str(i))
            n.setObjectName("stepNum")
            n.setFixedSize(22, 22)
            n.setAlignment(Qt.AlignCenter)
            r.addWidget(n)
            st = label(title, wrap=True)
            st.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            r.addWidget(st, 1)
            sv.addLayout(r)
        sv.addStretch(1)                        # buttons sit at the bottom of the card
        sv.addWidget(hline())
        sv.addSpacing(6)
        row = QHBoxLayout()
        b = push("Guided setup…", icon_name="wizard")
        b.setToolTip("Answer a few questions – gas, gap, drive, circuit – and get a ready-to-run model (Ctrl+N)")
        b.clicked.connect(self.newWizard.emit)
        row.addWidget(b)
        b = push("Open a model…", icon_name="open")
        b.setToolTip("Open a saved .p1d.json model file (Ctrl+O)")
        b.clicked.connect(self.openModel.emit)
        row.addWidget(b)
        sv.addLayout(row)
        self.recent_box = QWidget()
        rl = QVBoxLayout(self.recent_box)
        rl.setContentsMargins(0, 8, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(label("RECENT", "sectionTitle"))
        self.recent_lay = QVBoxLayout()
        self.recent_lay.setSpacing(0)
        rl.addLayout(self.recent_lay)
        sv.addWidget(self.recent_box)
        sv.addSpacing(4)
        lb = push("New here? Watch a 1-minute demo run", "link", icon_name="play", icon_color=T.c("accent"))
        lb.setToolTip("Runs a coarse version of the nitrogen nanosecond-pulse DBD benchmark and shows the live "
                      "plots. The quick start and tutorial are under Help.")
        lb.clicked.connect(lambda: self.demoCase.emit("config_case_nitrogen_pulsed_discharge"))
        sv.addWidget(lb)
        sidecol = QVBoxLayout()                 # left: what it simulates + other ways to start
        sidecol.setContentsMargins(0, 0, 0, 0)
        sidecol.setSpacing(8)                   # same heading + spacing as the case column, so the tops line up
        self.h_left = label("Simulate gas breakdown and discharges in a 1D gap", "h3", wrap=True)
        self.h_left.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        sidecol.addWidget(self.h_left)
        sidecol.addWidget(side, 1)
        sidebox = QWidget()
        sidebox.setLayout(sidecol)
        sidebox.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        main.addWidget(sidebox, 2)              # no AlignTop: both columns get the same height
        main.addWidget(cases, 3)
        v.addLayout(main)
        v.addStretch()
        self._rows = []
        self.populate()

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        QTimer.singleShot(0, self._level_headings)

    def _level_headings(self):
        """Both column headings get the same height, so the two boxes below them start level."""
        hs = [h.heightForWidth(max(h.width(), 50)) for h in (self.h_left, self.h_right)]
        for h in (self.h_left, self.h_right):
            h.setAlignment(Qt.AlignLeft | Qt.AlignBottom)    # each heading sits right above its box
            h.setFixedHeight(max(hs))

    def populate(self):
        for r in self._rows:
            self.case_lay.removeWidget(r)
            r.hide()
            r.deleteLater()
        self._rows = []
        cases = S.list_cases()
        cases = sorted(cases, key=lambda c: c.module != RECOMMENDED)       # the recommended case first
        for info in cases:
            row = CaseRow(info, self.openCase.emit, self.demoCase.emit)
            row.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            self.case_lay.addWidget(row)
            self._rows.append(row)
        self.refresh_recent()

    def refresh_recent(self):
        while self.recent_lay.count():
            w = self.recent_lay.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        items = [p for p in (self.settings.value("recent", []) or []) if p and Path(p).is_file()]
        for p in items[:5]:
            b = push(Path(p).name.replace(".p1d.json", ""), "link", icon_name="model", icon_color=T.c("text2"))
            b.setToolTip(p)
            b.clicked.connect(lambda _=None, pp=p: self.openRecent.emit(pp))
            self.recent_lay.addWidget(b)
        self.recent_box.setVisible(bool(items))          # no empty placeholder when there is nothing to show
