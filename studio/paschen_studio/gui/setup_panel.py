"""Model page, *Setup* mode: the few settings most studies change, in the order a user thinks about the
problem – gas, gap, applied voltage, circuit, electrodes, run length – as one short form.

This is the first level of progressive disclosure. Every card links to the complete block in *All settings*
(the second level), and only the settings that matter for the current choices are shown (e.g. τ and t_peak
only for a Gaussian pulse, R_m only for circuits that contain it).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from .. import schema as SC
from .. import solver as S
from . import icons
from . import theme as T
from .form import SettingsForm
from .widgets import label, push

# (title, icon, block opened by "More … settings", preview tab group, settings, one-line purpose)
SETUP_CARDS = [
    ("Gas", "gas", "plasma_state", "plasma_state",
     ["plasma_state.gas", "plasma_state.p_Torr", "plasma_state.T_i", "plasma_state.n0"],
     "Neutral gas, pressure and temperature, and the seed plasma."),
    ("Gap", "gap", "geometry", "geometry",
     ["geometry.L", "geometry.A", "geometry.l", "geometry.eps_r"],
     "Electrode spacing and area; a dielectric layer makes it a DBD."),
    ("Applied voltage", "wave", "waveform", "waveform",
     None,                                          # the whole block: only the chosen waveform's settings show
     "The source voltage V_app(t)."),
    ("External circuit", "circuit", "circuit", "circuit",
     ["circuit.circuit_type", "circuit.R0", "circuit.C_s", "circuit.L_s", "circuit.C_p", "circuit.L_p",
      "circuit.R_m", "circuit.C_ext"],
     "Elements between the source and the gap (only those of the chosen topology are shown)."),
    ("Electrodes", "emission", "emission", "emission",
     ["emission.gamma", "emission.enable_external_emission", "emission.enable_cathode_external_emission",
      "emission.enable_anode_external_emission"],
     "Secondary emission and optional external emission; the mechanisms (laser, field, thermionic …) and "
     "their parameters are under More electrodes settings."),
    ("Run length & resolution", "clock", "numerics", "numerics",
     ["run.T_total", "numerics.Nx", "numerics.Nt", "output.save_every", "run.run_name"],
     "How long to simulate, how fine the grid and time step are, how often to save."),
]


def setup_paths(model) -> set[str]:
    out = set()
    for _, _, g, _, paths, _ in SETUP_CARDS:
        if paths is None:
            gi = model.schema.groups.get(g)
            paths = [f.path for f in gi.fields] if gi else []
        out.update(p for p in paths if p in model.schema.fields)
    return out


class _Card(QFrame):
    def __init__(self, title, icon, group, intro, on_more, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.group = group
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 10)
        v.setSpacing(4)
        h = QHBoxLayout()
        h.setSpacing(8)
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon, T.c("accent"), 18))
        h.addWidget(ic)
        t = label(title, "h3")
        h.addWidget(t)
        h.addStretch()
        more = push(f"More {title.lower().split(' &')[0]} settings", "link", icon_name="chevron_right",
                    icon_color=T.c("accent"))
        more.setLayoutDirection(Qt.RightToLeft)
        more.setToolTip(f"Open the complete “{SC.GROUP_TITLES.get(group, group)}” block in All settings")
        more.clicked.connect(lambda: on_more(group))
        h.addWidget(more)
        v.addLayout(h)
        t.setToolTip(intro)                      # the purpose is one hover away, not another line to read
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 4, 0, 0)
        v.addLayout(self.body)


class SetupPanel(QWidget):
    changed = Signal(str, object)
    reset = Signal(str)
    action = Signal(str)
    more = Signal(str)                # open this block in All settings
    preview = Signal(str)             # show the preview for this block
    titleChanged = Signal(str)
    changeCase = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = None
        self.forms: list[tuple[str, SettingsForm]] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll)
        self.body = QWidget()
        self.lay = QVBoxLayout(self.body)
        self.lay.setContentsMargins(2, 0, 8, 8)
        self.lay.setSpacing(10)
        # model identity: one compact line (the header already shows the title in large type)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(label("Name", "muted"))
        self.title = QLineEdit()
        self.title.setToolTip("The model's name (also the default title of its runs)")
        self.title.setMaximumWidth(360)
        self.title.editingFinished.connect(lambda: self.titleChanged.emit(self.title.text().strip()))
        row.addWidget(self.title, 1)
        row.addStretch(1)
        self.lay.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.case_lab = label("", "muted")
        self.case_lab.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.addWidget(self.case_lab, 1)
        b = push("Change base case…", "link")
        b.setToolTip("Start from a different validated case and keep your changes where they still apply")
        b.clicked.connect(self.changeCase.emit)
        row.addWidget(b)
        self.lay.addLayout(row)
        self.cards_box = QVBoxLayout()
        self.cards_box.setSpacing(10)
        self.lay.addLayout(self.cards_box)
        self.lay.addWidget(label("Physics closures (transport, ionization, recombination), boundary conditions, "
                                 "numerical scheme and output options are under All settings.", "hint",
                                 wrap=True))
        self.lay.addStretch()
        self.scroll.setWidget(self.body)
        self._cards = []

    # ------------------------------------------------------------------------------------------
    def set_model(self, model):
        self.model = model
        for c in self._cards:
            self.cards_box.removeWidget(c)
            c.hide()
            c.deleteLater()
        self._cards, self.forms = [], []
        for title, icon, group, prev, paths, intro in SETUP_CARDS:
            if group not in model.schema.groups:
                continue
            card = _Card(title, icon, group, intro, self.more.emit)
            f = SettingsForm(model, group, paths=paths, compact=True, flat=True, minimal=True,
                             show_inactive=False, show_advanced=True)
            f.empty.setText("Nothing to set here for the current choices.")
            f.changed.connect(lambda p, v, g=prev: (self.preview.emit(g), self.changed.emit(p, v)))
            f.reset_requested.connect(self.reset.emit)
            f.action.connect(self.action.emit)
            card.body.addWidget(f)
            card.installEventFilter(self)
            self.cards_box.addWidget(card)
            self._cards.append(card)
            self.forms.append((prev, f))
            card.preview_group = prev
        self.refresh()

    def eventFilter(self, obj, ev):  # noqa: N802 - hovering a card shows its preview
        if ev.type() == ev.Type.Enter and getattr(obj, "preview_group", None):
            self.preview.emit(obj.preview_group)
        return super().eventFilter(obj, ev)

    def refresh(self):
        m = self.model
        if m is None:
            return
        if not self.title.hasFocus():
            self.title.setText(m.display_title())
        info = next((c for c in S.list_cases() if c.module == m.base_case), None)
        n = len(m.overrides)
        self.case_lab.setText(f"based on <b>{info.title if info else m.base_case}</b>"
                              + (f"  ·  {n} change{'s' * (n != 1)}" if n else ""))
        self.case_lab.setToolTip(f"{m.base_case}.py" + (f" – {n} setting(s) changed; see All settings → Overview"
                                                         if n else ""))
        for _, f in self.forms:
            f.refresh()

    def focus_field(self, path: str):
        for _, f in self.forms:
            if path in f.rows and f.rows[path].lab.isVisible():
                w = f.focus_field(path)
                if w is not None:
                    QTimer.singleShot(50, lambda: self.scroll.ensureWidgetVisible(w, 40, 80))
                return w
        return None
