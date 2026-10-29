"""Model Builder page: tree of setting groups, generated forms, previews and model check."""
from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSplitter,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from .. import advisor as A
from .. import schema as SC
from .. import solver as S
from ..units import format_quantity, human_bytes, human_duration
from . import icons
from . import theme as T
from .form import SettingsForm
from .previews import GraphicsPanel
from .setup_panel import SetupPanel
from .widgets import Collapsible, GuideText, SegmentedControl, StatTile, icon_button, label, push

OVERVIEW = "__overview__"


def pane(title: str = "", obj: str = "pane"):
    f = QFrame()
    f.setObjectName(obj)
    v = QVBoxLayout(f)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(0)
    head = QWidget()
    head.setObjectName("paneHeader")
    hl = QHBoxLayout(head)
    hl.setContentsMargins(14, 10, 10, 10)
    hl.setSpacing(6)
    t = label(title, "paneTitle")
    hl.addWidget(t)
    hl.addStretch()
    v.addWidget(head)
    return f, v, hl, t


# ---------------------------------------------------------------------------
class IssuesPanel(QFrame):
    """Model check as a slim status strip: one line says whether the model can run and what it will cost.
    The individual findings (with 'go to' and one-click fixes) fold out on demand, and open by themselves
    when a new error appears."""

    goto = Signal(str)
    fix = Signal(str)
    recheck = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("checkStrip")
        self._n_err = 0
        self._auto_opened = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(14, 7, 10, 7)
        hl.setSpacing(8)
        self.icon = QLabel()
        hl.addWidget(self.icon)
        self.state = label("", "paneTitle")
        hl.addWidget(self.state)
        self.summary = label("", "muted")
        self.summary.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        hl.addWidget(self.summary, 1)
        self.b_details = push("Details", "ghost", icon_name="chevron_up")
        self.b_details.setCheckable(True)
        self.b_details.setToolTip("Show every finding of the model check, with links and one-click fixes")
        self.b_details.toggled.connect(self._toggle)
        self.b_details.clicked.connect(lambda: setattr(self, "_auto_opened", False))    # user's choice wins
        hl.addWidget(self.b_details)
        b = icon_button("refresh", "Re-check the model now (Ctrl+Shift+K)", size=16)
        b.clicked.connect(self.recheck.emit)
        hl.addWidget(b)
        v.addWidget(head)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMaximumHeight(190)
        self.body = QWidget()
        self.lay = QVBoxLayout(self.body)
        self.lay.setContentsMargins(10, 0, 10, 8)
        self.lay.setSpacing(2)
        self.lay.addStretch()
        self.scroll.setWidget(self.body)
        self.scroll.setVisible(False)
        v.addWidget(self.scroll)

    def _toggle(self, on):
        self.scroll.setVisible(on)
        self.b_details.setIcon(icons.icon("chevron_down" if on else "chevron_up", T.c("text2"), 16))

    def mouseReleaseEvent(self, e):          # clicking the strip folds the details in/out
        if e.button() == Qt.LeftButton and e.position().y() < 44:
            self._auto_opened = False
            self.b_details.toggle()
        super().mouseReleaseEvent(e)

    def set_estimate(self, text: str):
        self._estimate = text
        self._update_summary()

    def _update_summary(self):
        est = getattr(self, "_estimate", "")
        ne, nw = self._n_err, getattr(self, "_n_warn", 0)
        if ne:
            txt = "Fix the errors below before running."
        elif nw:
            txt = (f"{nw} warning{'s' * (nw != 1)} worth a look" + (f"  ·  {est}" if est else ""))
        else:
            txt = est
        self.summary.setText(txt)

    def set_issues(self, issues):
        while self.lay.count() > 1:
            it = self.lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        cols = {"error": T.c("danger"), "warning": T.c("warning"), "info": T.c("text3"), "ok": T.c("success")}
        icn = {"error": "error", "warning": "warning", "info": "info", "ok": "ok"}
        ne = sum(1 for i in issues if i.level == "error")
        nw = sum(1 for i in issues if i.level == "warning")
        state = "error" if ne else ("warning" if nw else "ok")
        self.icon.setPixmap(icons.pixmap(icn[state], cols[state], 18))
        self.state.setText(f"{ne} error{'s' * (ne != 1)}" if ne else "Ready to run")
        self.state.setStyleSheet(f"color: {cols['error']};" if ne else "")
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)
        self.b_details.setText(f"Details ({len(issues)})" if issues else "Details")
        if ne > self._n_err and not self.b_details.isChecked():
            self._auto_opened = True
            self.b_details.setChecked(True)               # a new error: show it without being asked
        elif ne == 0 and self._auto_opened and self.b_details.isChecked():
            self._auto_opened = False
            self.b_details.setChecked(False)              # ...and fold it away again once it is fixed
        self._n_err, self._n_warn = ne, nw
        self._update_summary()
        for iss in issues:
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(2, 2, 2, 2)
            hl.setSpacing(8)
            ic = QLabel()
            ic.setPixmap(icons.pixmap(icn.get(iss.level, "info"), cols.get(iss.level, T.c("text3")), 16))
            ic.setAlignment(Qt.AlignTop)
            hl.addWidget(ic)
            msg = label(iss.message, wrap=True, selectable=True)
            if iss.level == "info":
                msg.setObjectName("muted")
            msg.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            hl.addWidget(msg, 1)
            if iss.fix:
                b = QPushButton(iss.fix_label or "Fix")
                b.setObjectName("fix")
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _=None, f=iss.fix: self.fix.emit(f))
                hl.addWidget(b, 0, Qt.AlignTop)
            if iss.path:
                g = icon_button("chevron_right", f"Go to {iss.path}", size=14)
                g.clicked.connect(lambda _=None, p=iss.path: self.goto.emit(p))
                hl.addWidget(g, 0, Qt.AlignTop)
            self.lay.insertWidget(self.lay.count() - 1, row)


# ---------------------------------------------------------------------------
class OverviewPanel(QWidget):
    """Model summary: title, key numbers and the list of changed settings."""

    titleChanged = Signal(str)
    descriptionChanged = Signal(str)
    goto = Signal(str)
    reset = Signal(str)
    changeCase = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = None
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(10)
        self.title = QLineEdit()
        self.title.setObjectName("titleEdit")
        self.title.setPlaceholderText("Model title")
        base = self.font().pointSizeF()
        self.title.setStyleSheet("QLineEdit#titleEdit { border: 1px solid transparent; background: transparent; "
                                 f"font-size: {base + 7:.1f}pt; font-weight: 700; padding: 2px 4px; }}"
                                 "QLineEdit#titleEdit:hover, QLineEdit#titleEdit:focus { border: 1px solid "
                                 f"{T.c('border2')}; background: {T.c('input')}; }}")
        self.title.setToolTip("Click to rename the model")
        self.title.editingFinished.connect(lambda: self.titleChanged.emit(self.title.text().strip()))
        v.addWidget(self.title)
        caseRow = QHBoxLayout()
        self.case_lab = label("", "muted", wrap=True)
        self.case_lab.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        caseRow.addWidget(self.case_lab, 1)
        b = push("Change base case…", "ghost", icon_name="layers")
        b.clicked.connect(self.changeCase.emit)
        caseRow.addWidget(b)
        caseRow.addStretch()
        v.addLayout(caseRow)
        self.desc = QPlainTextEdit()
        self.desc.setObjectName("input")
        self.desc.setPlaceholderText("Notes / description of this model (saved in the model file)")
        self.desc.setMaximumHeight(64)
        self.desc.textChanged.connect(lambda: self.descriptionChanged.emit(self.desc.toPlainText()))
        v.addWidget(self.desc)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.tiles = {}
        # the physics at a glance; run time and output size are in the model-check strip below
        specs = [("gas", "Gas", "gas"), ("gap", "Gap", "gap"), ("drive", "Drive", "wave"),
                 ("circuit", "Circuit", "circuit"), ("time", "Simulated time", "clock"),
                 ("breakdown", "Breakdown voltage", "bolt")]
        for k, (key, title, ic) in enumerate(specs):
            t = StatTile(title, "–", "", ic)
            self.tiles[key] = t
            grid.addWidget(t, k // 3, k % 3)
        v.addLayout(grid)
        v.addWidget(label("CHANGED SETTINGS", "sectionTitle"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Setting", "Case default", "This model", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setMinimumWidth(10)
        self.table.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.cellDoubleClicked.connect(lambda r, c: self.goto.emit(self.table.item(r, 0).data(Qt.UserRole)))
        self.empty = label("No settings changed yet – this model equals the base case. Pick a block on the left "
                           "to edit it; every change is listed here.", "muted", wrap=True)
        v.addWidget(self.empty)
        v.addWidget(self.table, 1)
        self.filler = QWidget()                 # keeps the empty-state text under its heading
        self.filler.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        v.addWidget(self.filler)

    def set_model(self, model):
        self.model = model
        self.refresh()

    def refresh(self):
        m = self.model
        if m is None:
            return
        if not self.title.hasFocus():
            self.title.setText(m.display_title() if m.title or m.path else m.display_title())
        if not self.desc.hasFocus():
            self.desc.blockSignals(True)
            self.desc.setPlainText(m.description or "")
            self.desc.blockSignals(False)
        info = next((c for c in S.list_cases() if c.module == m.base_case), None)
        self.case_lab.setText(f"Base case: <b>{info.title if info else m.base_case}</b>  "
                              f"<span style='color:gray'>({m.base_case}.py)</span>")
        v = m.values()
        e = A.estimate(m)
        self.tiles["gas"].set(f"{str(v['plasma_state.gas']).capitalize()}",
                              f"{v['plasma_state.p_Torr']:.4g} Torr · Tᵢ = {v['plasma_state.T_i']:g} K")
        self.tiles["gap"].set(format_quantity(v["geometry.L"], "m"),
                              f"pd = {e['pd_Torr_cm']:.3g} Torr·cm · A = {v['geometry.A'] * 1e4:.3g} cm²")
        wt = v["waveform.waveform_type"]
        self.tiles["drive"].set(format_quantity(v["waveform.V_peak"], "V"),
                                f"{SC.choice_label(wt)} · E/N ≈ {e['E_over_N_Td']:.3g} Td")
        self.tiles["circuit"].set(SC.choice_label(v["circuit.circuit_type"]).split(" (")[0],
                                  SC.choice_label(v["circuit.circuit_time_scheme"]))
        self.tiles["time"].set(format_quantity(v["run.T_total"], "s"),
                               f"{e['Nt'] - 1:,} steps of {format_quantity(e['dt'], 's')} · {e['Nx']} grid points")
        try:
            pc = A.paschen_curve(m, npts=8)
            if pc and math.isfinite(pc["Vb0"]):
                Vop = abs(float(v["waveform.V_peak"]))
                self.tiles["breakdown"].set(format_quantity(pc["Vb0"], "V"),
                                            f"V_peak / V_b = {Vop / pc['Vb0']:.2f} (classical Townsend)")
            else:
                self.tiles["breakdown"].set("–", "no Townsend breakdown at this pd")
        except Exception:
            self.tiles["breakdown"].set("–", "")
        rows = m.summary_rows()
        self.table.setRowCount(len(rows))
        for i, (p, d, val) in enumerate(rows):
            fi = m.schema.fields.get(p)
            meta = SC.meta_for(p, fi.comment if fi else "")
            g = p.rpartition(".")[0]
            it = QTableWidgetItem(f"{meta.label}  ·  {SC.GROUP_TITLES.get(g, g)}")
            it.setData(Qt.UserRole, p)
            it.setToolTip(p)
            it.setIcon(icons.icon(SC.GROUP_ICONS.get(g, "dot"), T.c("accent"), 14))
            self.table.setItem(i, 0, it)
            self.table.setItem(i, 1, QTableWidgetItem(d))
            vi = QTableWidgetItem(val)
            vi.setForeground(QColor(T.c("accent")))
            f = vi.font()
            f.setBold(True)
            vi.setFont(f)
            self.table.setItem(i, 2, vi)
            b = icon_button("reset", "Reset to case default", size=14)
            b.clicked.connect(lambda _=None, pp=p: self.reset.emit(pp))
            self.table.setCellWidget(i, 3, b)
        self.table.setColumnWidth(3, 36)
        self.table.setVisible(bool(rows))
        self.empty.setVisible(not rows)
        self.filler.setVisible(not rows)


# ---------------------------------------------------------------------------
class ModelPage(QWidget):
    modelEdited = Signal(list)          # changed paths
    statusMessage = Signal(str)
    requestChangeCase = Signal()
    requestIonBrowser = Signal()
    requestFix = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.model = None
        self.workspace = None
        self.group = OVERVIEW
        self.form: SettingsForm | None = None
        self.issues = []
        # Two levels (progressive disclosure): Setup = the few settings most studies change, as one short
        # form in the user's order; All settings = every solver block (tree), for experts.
        self.show_all = str(settings.value("settings_view", "setup")) == "all"
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.view = SegmentedControl(
            ["Setup", "All settings"],
            ["The settings most studies change – gas, gap, voltage, circuit, electrodes, run length – as one "
             "short form, with the live preview.",
             "Every solver setting, block by block: physics closures, boundary conditions, numerics, output, "
             "expert options (unused ones greyed, with the reason)."],
            current=1 if self.show_all else 0)
        self.view.setFixedWidth(240)
        self.view.changed.connect(lambda i: self.set_show_all(i == 1))
        bar.addWidget(self.view)
        self.view_hint = label("", "hint")
        bar.addWidget(self.view_hint, 1)
        self.find_btn = QPushButton("  Find a setting…")
        self.find_btn.setIcon(icons.icon("search", T.c("text3"), 15))
        self.find_btn.setStyleSheet(f"QPushButton {{ text-align: left; color: {T.c('text3')}; font-weight: 500; "
                                    f"background: {T.c('surface')}; padding: 5px 10px; }}")
        self.find_btn.setMinimumWidth(220)
        self.find_btn.setToolTip("Search every setting by name or meaning (Ctrl+K)")
        bar.addWidget(self.find_btn)
        root.addLayout(bar)
        self.modes = QStackedWidget()
        root.addWidget(self.modes, 1)
        # Setup mode: form | preview
        self.ssplit = QSplitter(Qt.Horizontal)
        self.ssplit.setChildrenCollapsible(False)
        self.setup = SetupPanel()
        self.setup.changed.connect(self._changed)
        self.setup.reset.connect(self._reset_one)
        self.setup.action.connect(self._form_action)
        self.setup.more.connect(self.open_block)
        self.setup.preview.connect(lambda g: self.graphics.show_for_group(g))
        self.setup.titleChanged.connect(self._title)
        self.setup.changeCase.connect(self.requestChangeCase.emit)
        self.setup.setMinimumWidth(460)
        self.ssplit.addWidget(self.setup)
        self.modes.addWidget(self.ssplit)
        # All settings mode: tree | block | preview
        self.hsplit = QSplitter(Qt.Horizontal)
        self.hsplit.setChildrenCollapsible(False)
        self.modes.addWidget(self.hsplit)

        # ---- tree ----
        left, lv, lh, _ = pane("Blocks")
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(10)
        self.tree.setIconSize(QSize(17, 17))
        self.tree.setRootIsDecorated(False)
        self.tree.itemSelectionChanged.connect(self._on_tree)
        lv.addWidget(self.tree, 1)
        self.changes_lab = label("", "hint", wrap=True)
        cl = QWidget()
        cll = QVBoxLayout(cl)
        cll.setContentsMargins(14, 6, 10, 10)
        cll.setSpacing(2)
        cll.addWidget(self.changes_lab)
        self.hidden_link = push("", "link")
        self.hidden_link.setToolTip("Show every block, including those the current choices do not use")
        self.hidden_link.clicked.connect(lambda: self.set_show_all(True))
        self.hidden_link.hide()
        cll.addWidget(self.hidden_link)
        lv.addWidget(cl)
        left.setMinimumWidth(220)
        self.hsplit.addWidget(left)

        # ---- settings ----
        mid, mv, mh, self.mid_title = pane("Settings")
        self.mid_icon = QLabel()
        mh.insertWidget(0, self.mid_icon)
        # only shown when this block has changed settings (nothing to reset otherwise)
        self.b_reset = icon_button("reset", "Reset every setting of this block to the case defaults", size=16,
                                   text="Reset block")
        mh.addWidget(self.b_reset)
        self.b_reset.clicked.connect(self._reset_group)
        self.intro = label("", "muted", wrap=True)
        iw = QWidget()
        il = QVBoxLayout(iw)
        il.setContentsMargins(16, 10, 16, 0)
        il.addWidget(self.intro)
        self.inactive_banner = label("", "hint", wrap=True)
        il.addWidget(self.inactive_banner)
        mv.addWidget(iw)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        mv.addWidget(self.scroll, 1)
        mid.setMinimumWidth(420)
        self._mid = mid
        mid.installEventFilter(self)
        self.hsplit.addWidget(mid)

        # ---- graphics ----
        right, rv, rh, _ = pane("Preview")
        self.graphics = GraphicsPanel()
        gw = QWidget()
        gl = QVBoxLayout(gw)
        gl.setContentsMargins(8, 0, 8, 8)
        gl.addWidget(self.graphics)
        rv.addWidget(gw, 1)
        right.setMinimumWidth(320)
        self.preview_pane = right
        self.hsplit.addWidget(right)
        self.hsplit.setSizes([250, 560, 560])
        self.hsplit.setStretchFactor(1, 1)
        self.hsplit.setStretchFactor(2, 1)
        self._place_preview()

        # ---- model check: a slim strip, details on demand ----
        self.issues_panel = IssuesPanel()
        self.issues_panel.goto.connect(self.focus_setting)
        self.issues_panel.fix.connect(self.requestFix.emit)
        self.issues_panel.recheck.connect(lambda: self.run_check(deep=True))
        root.addWidget(self.issues_panel)

        self.overview = OverviewPanel()
        self.overview.titleChanged.connect(self._title)
        self.overview.descriptionChanged.connect(self._desc)
        self.overview.goto.connect(self.focus_setting)
        self.overview.reset.connect(self._reset_one)
        self.overview.changeCase.connect(self.requestChangeCase.emit)

        self._check_timer = QTimer(self)
        self._check_timer.setSingleShot(True)
        self._check_timer.setInterval(700)
        self._check_timer.timeout.connect(lambda: self.run_check(deep=True))

    # -- header fitting -----------------------------------------------------------
    def eventFilter(self, obj, ev):  # noqa: N802
        if obj is getattr(self, "_mid", None) and ev.type() == QEvent.Resize:
            QTimer.singleShot(0, self._fit_mid_header)
        return super().eventFilter(obj, ev)

    def _fit_mid_header(self):
        """Show the block title in full; drop the button captions (icons + tooltips stay) when space is short."""
        btns = [b for b in (self.b_reset,) if b.isVisible()]
        if not btns:
            return
        fm = self.mid_title.fontMetrics()
        title_w = fm.horizontalAdvance(self.mid_title.text()) + 60          # icon, margins, spacing
        full = sum(b.fontMetrics().horizontalAdvance(b.text()) + 44 for b in btns)
        compact = title_w + full > self._mid.width()
        style = Qt.ToolButtonIconOnly if compact else Qt.ToolButtonTextBesideIcon
        for b in btns:
            if b.toolButtonStyle() != style:
                b.setToolButtonStyle(style)

    # -- model -------------------------------------------------------------------
    def set_model(self, model, workspace=None):
        self.model = model
        self.workspace = workspace
        self.overview.set_model(model)
        self.setup.set_model(model)
        self.graphics.set_model(model)
        self._build_tree()
        self.select_group(self.group if self.group == OVERVIEW or self.group in model.schema.groups else OVERVIEW)
        self.run_check(deep=True)

    def _build_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        self._items = {}
        it = QTreeWidgetItem(["Overview"])
        it.setData(0, Qt.UserRole, OVERVIEW)
        it.setIcon(0, icons.icon("home", T.c("accent"), 17))
        f = it.font(0)
        f.setBold(True)
        it.setFont(0, f)
        self.tree.addTopLevelItem(it)
        self._items[OVERVIEW] = it
        groups = self.model.schema.groups
        for sec, items in SC.TREE:
            head = QTreeWidgetItem([sec.upper()])
            head.setFlags(Qt.ItemIsEnabled)
            hf = QFont(head.font(0))
            hf.setBold(True)
            hf.setPointSizeF(max(7.0, hf.pointSizeF() - 1.5))
            head.setFont(0, hf)
            head.setForeground(0, QColor(T.c("text3")))
            self.tree.addTopLevelItem(head)
            for g, title, ic in items:
                if g not in groups or not groups[g].fields:
                    continue
                c = QTreeWidgetItem([title])
                c.setData(0, Qt.UserRole, g)
                head.addChild(c)
                self._items[g] = c
            head.setExpanded(True)
        # groups unknown to the studio (new solver releases)
        known = {g for _, its in SC.TREE for g, _, _ in its}
        extra = [g for g, gi in groups.items() if g not in known and gi.fields]
        if extra:
            head = QTreeWidgetItem(["OTHER"])
            head.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(head)
            for g in extra:
                c = QTreeWidgetItem([SC.humanize(g.replace(".", " "))])
                c.setData(0, Qt.UserRole, g)
                head.addChild(c)
                self._items[g] = c
            head.setExpanded(True)
        self.tree.blockSignals(False)
        self._decorate_tree()

    def _decorate_tree(self):
        if self.model is None:
            return
        v = self.model.values()
        counts = {}
        for p in self.model.overrides:
            g = p.rpartition(".")[0]
            counts[g] = counts.get(g, 0) + 1
        errs = {}
        for iss in self.issues:
            if iss.level == "error" and iss.path:
                g = iss.path.rpartition(".")[0]
                errs[g] = errs.get(g, 0) + 1
        hidden = 0
        for g, it in self._items.items():
            if g == OVERVIEW:
                continue
            active, why = SC.group_active(g, v)
            keep = True                               # All settings lists every block (unused ones greyed)
            it.setHidden(not keep)
            hidden += not keep
            title = SC.GROUP_TITLES.get(g, SC.humanize(g))
            n = counts.get(g, 0)
            it.setText(0, title + (f"   •{n}" if n else ""))
            col = T.c("danger") if errs.get(g) else (T.c("accent") if active else T.c("text3"))
            it.setIcon(0, icons.icon("error" if errs.get(g) else SC.GROUP_ICONS.get(g, "dot"), col, 17))
            it.setForeground(0, QColor(T.c("text") if active else T.c("text3")))
            it.setToolTip(0, (why if not active else SC.GROUP_INTRO.get(g, "")) +
                          (f"\n{n} changed setting(s)" if n else ""))
        for i in range(self.tree.topLevelItemCount()):          # section titles follow their blocks
            head = self.tree.topLevelItem(i)
            if head.childCount():
                head.setHidden(all(head.child(k).isHidden() for k in range(head.childCount())))
        n = len(self.model.overrides)
        self.changes_lab.setText(f"{n} setting{'s' * (n != 1)} changed from the base case" if n else
                                 "Using the base-case defaults")
        self.hidden_link.setText(f"+ {hidden} more block{'s' * (hidden != 1)} in All settings")
        self.hidden_link.setVisible(hidden > 0)

    def _on_tree(self):
        it = self.tree.currentItem()
        if it is None:
            return
        g = it.data(0, Qt.UserRole)
        if g:
            self.select_group(g, from_tree=True)

    def select_group(self, g: str, from_tree: bool = False):
        self.group = g
        if not from_tree and g in self._items:
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(self._items[g])
            self.tree.blockSignals(False)
        old = self.scroll.takeWidget()
        if old is not None and old is not self.overview:
            old.deleteLater()
        if g == OVERVIEW:
            self.mid_title.setText("Overview")
            self.mid_icon.setPixmap(icons.pixmap("home", T.c("accent"), 18))
            self.intro.setText("Everything about this model at a glance. Double-click a changed setting to edit it.")
            self.inactive_banner.setVisible(False)
            self.b_reset.setVisible(False)
            self.overview.refresh()
            self.scroll.setWidget(self.overview)
            self.overview.show()
            self.form = None
            return
        self._update_reset_button()
        title = SC.GROUP_TITLES.get(g, SC.humanize(g))
        self.mid_title.setText(title)
        QTimer.singleShot(0, self._fit_mid_header)
        self.mid_icon.setPixmap(icons.pixmap(SC.GROUP_ICONS.get(g, "dot"), T.c("accent"), 18))
        self.intro.setText(SC.GROUP_INTRO.get(g, self.model.schema.groups[g].doc))
        active, why = SC.group_active(g, self.model.values())
        self.inactive_banner.setText(f"⚠ This block is not used right now: {why}")
        self.inactive_banner.setVisible(not active)
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 8, 16, 16)
        # All settings: every option incl. expert ones; settings unused by the current choices fold behind one
        # link at the end of the block (a wholly unused block shows everything, dimmed, with the reason)
        self.form = SettingsForm(self.model, g, show_inactive=not active, show_advanced=True)
        self.form.changed.connect(self._changed)
        self.form.reset_requested.connect(self._reset_one)
        self.form.action.connect(self._form_action)
        bl.addWidget(self.form)
        guide = self.model.schema.groups[g].guide
        if guide:
            col = Collapsible("Learn more", False)
            col.btn.setToolTip("Background notes from the PASCHEN-1D configuration guide")
            col.body_lay.addWidget(GuideText(guide))
            bl.addSpacing(8)
            bl.addWidget(col)
        bl.addStretch(1)                       # extra height goes below the content, not inside the form
        self.scroll.setWidget(body)
        self.graphics.show_for_group(g)
        if self._items.get(g) is not None and self._items[g].isHidden():
            self._decorate_tree()                 # a block reached by search/links is always listed

    def set_show_all(self, on: bool):
        """Setup (False) or All settings (True)."""
        on = bool(on)
        self.view.setIndex(1 if on else 0)
        changed = on != self.show_all
        self.show_all = on
        self.settings.setValue("settings_view", "all" if on else "setup")
        self._place_preview()
        if self.model is not None and changed:
            if on:
                self._decorate_tree()
                self.select_group(self.group)
            else:
                self.setup.refresh()

    def _place_preview(self):
        """One preview panel, shown beside whichever mode is active."""
        target = self.hsplit if self.show_all else self.ssplit
        if self.preview_pane.parent() is not target:
            target.addWidget(self.preview_pane)
            if target is self.ssplit:
                self.ssplit.setSizes([620, 560])
                self.ssplit.setStretchFactor(0, 1)
                self.ssplit.setStretchFactor(1, 1)
            else:
                self.hsplit.setSizes([250, 560, 560])
        self.modes.setCurrentIndex(1 if self.show_all else 0)
        self.view_hint.setText("Every solver setting, block by block." if self.show_all else
                               "The settings most studies change. Everything else is under All settings.")

    def open_block(self, g: str):
        """'More … settings' from a Setup card: the complete block in All settings."""
        self.set_show_all(True)
        self.select_group(g)

    def _update_reset_button(self):
        g = self.group
        n = sum(1 for p in self.model.overrides if p.rpartition(".")[0] == g) if (self.model and g != OVERVIEW) else 0
        self.b_reset.setVisible(n > 0)
        if n:
            QTimer.singleShot(0, self._fit_mid_header)

    # -- editing -------------------------------------------------------------------
    def _changed(self, path, value):
        if self.model.set(path, value):
            self.after_edit([path])

    def _reset_one(self, path):
        if self.model.reset(path):
            self.after_edit([path])

    def _reset_group(self):
        if self.group and self.group != OVERVIEW:
            ch = self.model.reset_group(self.group)
            if ch:
                self.after_edit(ch)

    def _title(self, t):
        if t and t != self.model.title:
            self.model.title = t
            self.modelEdited.emit([])

    def _desc(self, t):
        if t != (self.model.description or ""):
            self.model.description = t
            self.modelEdited.emit([])

    def _form_action(self, name):
        if name == "auto_gas":
            self.requestFix.emit("auto_gas")
        elif name == "ion_browser":
            self.requestIonBrowser.emit()

    def after_edit(self, paths):
        """Refresh everything that depends on the model after a change."""
        if self.form is not None:
            self.form.refresh()
            active, why = SC.group_active(self.group, self.model.values()) if self.group != OVERVIEW else (True, "")
            self.inactive_banner.setVisible(not active)
            self.inactive_banner.setText(f"⚠ This block is not used right now: {why}")
            self._update_reset_button()
        else:
            self.overview.refresh()
        self.setup.refresh()
        self.graphics.invalidate(paths)
        self._decorate_tree()
        self.modelEdited.emit(list(paths))
        if str(self.settings.value("auto_check", "true")).lower() == "true":
            self.run_check(deep=False)
            self._check_timer.start()

    def refresh_all(self):
        if self.group == OVERVIEW or self.form is None:
            self.overview.refresh()
        else:
            self.form.refresh()
        self.setup.refresh()
        self.graphics.invalidate()
        self._decorate_tree()
        self.run_check(deep=False)

    def run_check(self, deep: bool = True):
        if self.model is None:
            return []
        self.issues = A.check_model(self.model, workspace=self.workspace, deep=deep,
                                    measured_rate_coeff=_float(self.settings.value("rate_coeff", None)))
        self.issues_panel.set_issues(self.issues)
        try:
            e = A.estimate(self.model)
            self.issues_panel.set_estimate(f"estimated run time ≈ {human_duration(e['runtime_s'])}  ·  "
                                           f"output ≈ {human_bytes(e['bytes_total'])}  ·  "
                                           f"{e['Nt'] - 1:,} time steps × {e['Nx']} grid points")
        except Exception:
            self.issues_panel.set_estimate("")
        self._decorate_tree()
        return self.issues

    def focus_setting(self, path: str):
        if not path or self.model is None or path not in self.model.schema.fields:
            return
        g = path.rpartition(".")[0]
        if g not in self._items:
            return
        if not self.show_all:                    # stay in Setup if the setting is on the Setup form
            w = self.setup.focus_field(path)
            if w is not None:
                self._flash(w)
                return
            self.set_show_all(True)              # otherwise reveal it in All settings
        self.select_group(g)
        if self.form is not None:
            w = self.form.focus_field(path)
            if w is not None:
                QTimer.singleShot(50, lambda: self.scroll.ensureWidgetVisible(w, 40, 80))
                self._flash(w)

    def _flash(self, w):
        w.setStyleSheet(f"background: {T.c('accent_soft')}; border-radius: 6px;")
        QTimer.singleShot(1200, lambda: w.setStyleSheet(""))

    def restyle(self):
        self.graphics.restyle()
        if self.model is not None:
            self._build_tree()
            self.setup.set_model(self.model)
            self.select_group(self.group)
            self.issues_panel.set_issues(self.issues)


def _float(x):
    try:
        return float(x) if x not in (None, "") else None
    except (TypeError, ValueError):
        return None
