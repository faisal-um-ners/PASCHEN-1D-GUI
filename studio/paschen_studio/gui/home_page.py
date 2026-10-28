"""Home page: start points for new and experienced users."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from .. import (APP_DESCRIPTION, APP_NAME, APP_TAGLINE, PAPER_URL, REPO_URL, __version__)
from .. import advisor as A
from .. import solver as S
from ..model import StudioModel
from ..units import human_duration
from . import icons
from . import theme as T
from .widgets import ElidedLabel, FlowLayout, chip, label, push

CASE_ICONS = {
    "config_case_nitrogen_pulsed_discharge": ("bolt", "#7c3aed"),
    "config_case_argon_dc_discharge": ("wave", "#2563eb"),
    "config_case_argon_photoemission_discharge": ("emission", "#db2777"),
    "config_case_deuterium_pulsed_discharge": ("atom", "#0891b2"),
    "config_case_helium_photoemission_discharge": ("gas", "#ea580c"),
    "config": ("book", "#64748b"),
}


class CaseCard(QFrame):
    def __init__(self, info, on_open, on_demo, parent=None):
        super().__init__(parent)
        self.setObjectName("cardHover")
        self.setCursor(Qt.PointingHandCursor)
        self.on_open = on_open
        self.info = info
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)
        top = QHBoxLayout()
        ic, col = CASE_ICONS.get(info.module, ("model", "#64748b"))
        bub = QLabel()
        bub.setFixedSize(40, 40)
        bub.setAlignment(Qt.AlignCenter)
        qc = QColor(col)
        bub.setStyleSheet(f"background: rgba({qc.red()},{qc.green()},{qc.blue()},0.13); border-radius: 10px;")
        bub.setPixmap(icons.pixmap(ic, col, 22))
        top.addWidget(bub)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        t = label(info.title)
        f = t.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() + 1)
        t.setFont(f)
        t.setWordWrap(True)
        tv.addWidget(t)
        mod = ElidedLabel(f"{info.module}.py")         # long module names elide instead of widening the card
        mod.setObjectName("faint")
        tv.addWidget(mod)
        top.addLayout(tv, 1)
        v.addLayout(top)
        s = label(info.summary, "muted", wrap=True)
        s.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
        v.addWidget(s)
        chips = QWidget()
        fl = FlowLayout(chips, 5, 5)
        for tg in info.tags:
            fl.addWidget(chip(tg))
        try:
            est = A.estimate(StudioModel(info.module))
            fl.addWidget(chip(f"≈ {human_duration(est['runtime_s'])}", accent=True))
        except Exception:
            pass
        v.addWidget(chips)
        v.addStretch()
        h = QHBoxLayout()
        b = push("Open case", "primary", icon_name="model")
        b.clicked.connect(lambda: on_open(info.module))
        h.addWidget(b)
        d = push("Quick demo", icon_name="play")
        d.setToolTip("Run a short, coarse version right away to see what this case does")
        d.clicked.connect(lambda: on_demo(info.module))
        h.addWidget(d)
        h.addStretch()
        v.addLayout(h)
        self.setMinimumHeight(220)

    def mouseDoubleClickEvent(self, e):
        self.on_open(self.info.module)


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
        v.setContentsMargins(28, 22, 28, 28)
        v.setSpacing(18)

        # hero
        hero = QFrame()
        hero.setObjectName("hero")
        hv = QHBoxLayout(hero)
        hv.setContentsMargins(30, 26, 30, 26)
        left = QVBoxLayout()
        left.setSpacing(8)
        row = QHBoxLayout()
        lg = QLabel()
        lg.setPixmap(icons.logo_pixmap(54))
        row.addWidget(lg)
        tt = QVBoxLayout()
        tt.setSpacing(0)
        h1 = label(APP_NAME, "h1")
        tt.addWidget(h1)
        sub = label(APP_TAGLINE, "heroSub")
        tt.addWidget(sub)
        row.addLayout(tt)
        row.addStretch()
        left.addLayout(row)
        d = label(APP_DESCRIPTION + " Build a model with guided forms, check it, run it with live plots, and "
                  "analyse the results – without writing code.", "heroSub", wrap=True)
        d.setMaximumWidth(820)
        d.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
        d.setMinimumHeight(48)
        left.addWidget(d)
        left.addSpacing(6)
        bh = QHBoxLayout()
        b1 = QPushButton("  New simulation – guided")
        b1.setObjectName("heroPrimary")
        b1.setIcon(icons.icon("wizard", "#1e3a8a", 18))
        b1.setIconSize(QSize(18, 18))
        b1.clicked.connect(self.newWizard.emit)
        b2 = QPushButton("  Open model…")
        b2.setObjectName("heroGhost")
        b2.setIcon(icons.icon("open", "#ffffff", 18))
        b2.clicked.connect(self.openModel.emit)
        b3 = QPushButton("  1-minute demo")
        b3.setObjectName("heroGhost")
        b3.setIcon(icons.icon("play", "#ffffff", 18))
        b3.setToolTip("Runs a coarse version of the nitrogen nanosecond-pulse DBD benchmark and opens the live monitor")
        b3.clicked.connect(lambda: self.demoCase.emit("config_case_nitrogen_pulsed_discharge"))
        for b in (b1, b2, b3):
            b.setCursor(Qt.PointingHandCursor)
            bh.addWidget(b)
        bh.addStretch()
        left.addLayout(bh)
        hv.addLayout(left, 1)
        hero.setMinimumHeight(250)
        v.addWidget(hero)

        # cases
        hdr = QHBoxLayout()
        hdr.addWidget(label("Start from a validated case", "h2"))
        hdr.addSpacing(16)
        sub = label("Every case is a complete PASCHEN-1D configuration module. Open it, change what you "
                    "need, run.", "muted", wrap=True)
        sub.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hdr.addWidget(sub, 1)
        v.addLayout(hdr)
        self.grid = QGridLayout()
        self.grid.setSpacing(14)
        v.addLayout(self.grid)

        # bottom row
        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        rc = QFrame()
        rc.setObjectName("card")
        rl = QVBoxLayout(rc)
        rl.setContentsMargins(16, 14, 16, 14)
        rl.addWidget(label("Recent models", "h3"))
        self.recent = QListWidget()
        self.recent.setMinimumHeight(150)
        self.recent.itemActivated.connect(lambda it: self.openRecent.emit(it.data(Qt.UserRole)))
        self.recent.itemClicked.connect(lambda it: self.openRecent.emit(it.data(Qt.UserRole)))
        rl.addWidget(self.recent)
        self.recent_empty = label("Models you save or open appear here.", "muted")
        rl.addWidget(self.recent_empty)
        rl.addStretch()
        bottom.addWidget(rc, 1)

        lc = QFrame()
        lc.setObjectName("card")
        ll = QVBoxLayout(lc)
        ll.setContentsMargins(16, 14, 16, 14)
        ll.addWidget(label("How it works", "h3"))
        steps = [("model", "Pick a case or use the guided wizard."),
                 ("settings", "Adjust settings – every field explains itself, uses real units and shows only "
                              "what matters for your choices."),
                 ("check", "Check the model: solver validation plus advice and one-click fixes."),
                 ("play", "Run. Watch densities, fields, voltages and currents evolve live."),
                 ("results", "Explore results: snapshots, animation, space–time maps, comparisons, sweeps, "
                             "publication-quality export.")]
        for i, (ic, txt) in enumerate(steps, 1):
            h = QHBoxLayout()
            n = QLabel(str(i))
            n.setFixedSize(24, 24)
            n.setAlignment(Qt.AlignCenter)
            n.setStyleSheet(f"background: {T.c('accent_soft')}; color: {T.c('accent')}; border-radius: 12px; "
                            "font-weight: 700;")
            h.addWidget(n)
            h.addWidget(label(txt, wrap=True), 1)
            ll.addLayout(h)
        links = QHBoxLayout()
        for text, ic, act in (("Tutorial", "book", lambda: self.showHelp.emit("tutorial")),
                              ("Quick start", "help", lambda: self.showHelp.emit("quickstart")),
                              ("Paper", "quote", lambda: QDesktopServices.openUrl(QUrl(PAPER_URL))),
                              ("GitHub", "github", lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))):
            b = push(text, "ghost", icon_name=ic)
            b.clicked.connect(act)
            links.addWidget(b)
        links.addStretch()
        ll.addLayout(links)
        bottom.addWidget(lc, 1)
        v.addLayout(bottom)
        sv, sd = S.solver_version()
        foot = label(f"{APP_NAME} {__version__}  ·  PASCHEN-1D {sv} ({sd})  ·  solver folder: {S.solver_root()}",
                     "faint", wrap=True, selectable=True)
        v.addWidget(foot)
        v.addStretch()
        self._cards = []
        self._ncols = 3
        self._scroll = sc
        self.populate()

    def _columns_for(self, width: int) -> int:
        return 3 if width >= 3 * 300 + 28 else (2 if width >= 2 * 300 + 14 else 1)

    def _place_cards(self):
        for c in self._cards:
            self.grid.removeWidget(c)
        for i, card in enumerate(self._cards):
            self.grid.addWidget(card, i // self._ncols, i % self._ncols)
        for col in range(3):
            self.grid.setColumnStretch(col, 1 if col < self._ncols else 0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        n = self._columns_for(self._scroll.viewport().width() - 56)
        if n != self._ncols:
            self._ncols = n
            self._place_cards()

    def populate(self):
        for c in self._cards:
            self.grid.removeWidget(c)
            c.hide()
            c.deleteLater()
        self._cards = []
        cases = S.list_cases()
        for info in cases:
            self._cards.append(CaseCard(info, self.openCase.emit, self.demoCase.emit))
        self._place_cards()
        self.refresh_recent()

    def refresh_recent(self):
        self.recent.clear()
        items = [p for p in (self.settings.value("recent", []) or []) if p and Path(p).is_file()]
        for p in items[:8]:
            it = QListWidgetItem(icons.icon("model", T.c("accent"), 16), f"{Path(p).name}    —    {Path(p).parent}")
            it.setData(Qt.UserRole, p)
            self.recent.addItem(it)
        self.recent.setVisible(bool(items))
        self.recent_empty.setVisible(not items)
