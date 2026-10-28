"""Guided 'New simulation' wizard for users who are new to PASCHEN-1D."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from .. import advisor as A
from .. import schema as SC
from .. import solver as S
from ..model import StudioModel, new_model_from_case
from ..units import format_quantity, human_bytes, human_duration
from . import icons
from . import theme as T
from .form import SettingsForm
from .home_page import CASE_ICONS
from .plotting import PlotCanvas
from .previews import CircuitDiagram, DeviceSchematic, paschen_spec, waveform_spec
from .widgets import StatTile, label, push

STEPS = [
    ("Starting point", "model"),
    ("Gas & gap", "gas"),
    ("Applied voltage", "wave"),
    ("External circuit", "circuit"),
    ("Surface emission", "emission"),
    ("Duration & resolution", "clock"),
    ("Review", "check"),
]


class NewSimulationWizard(QDialog):
    def __init__(self, parent=None, workspace=None, start_case: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("New simulation")
        self.resize(1320, 820)
        self.workspace = workspace
        self.model: StudioModel | None = None
        self.run_after = False
        self._forms = []
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # stepper
        side = QFrame()
        side.setObjectName("navRail")
        side.setFixedWidth(230)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(16, 20, 12, 16)
        t = label("New simulation", "h3")
        t.setStyleSheet("color: white;")
        sv.addWidget(t)
        st = label("A few guided steps. You can change everything later in the Model Builder.", "hint", wrap=True)
        sv.addWidget(st)
        sv.addSpacing(12)
        self.step_btns = []
        for i, (name, ic) in enumerate(STEPS):
            b = QPushButton(f"  {i + 1}.  {name.replace('&', '&&')}")
            b.setCheckable(True)
            b.setIcon(icons.icon(ic, "#94a3b8", 16, active_color="#ffffff"))
            b.setStyleSheet("QPushButton { text-align: left; color: #94a3b8; background: transparent; border: none;"
                            " padding: 8px 6px; border-radius: 8px; font-weight: 600; }"
                            "QPushButton:checked { background: #1e293b; color: white; }"
                            "QPushButton:hover { color: white; }")
            b.clicked.connect(lambda _=None, k=i: self.go(k))
            sv.addWidget(b)
            self.step_btns.append(b)
        sv.addStretch()
        root.addWidget(side)
        # pages
        main = QWidget()
        mv = QVBoxLayout(main)
        mv.setContentsMargins(24, 20, 24, 16)
        self.head = label("", "h2")
        mv.addWidget(self.head)
        self.headsub = label("", "muted", wrap=True)
        mv.addWidget(self.headsub)
        self.stack = QStackedWidget()
        mv.addWidget(self.stack, 1)
        nav = QHBoxLayout()
        self.b_back = push("Back", icon_name="step_back")
        self.b_back.clicked.connect(lambda: self.go(self.stack.currentIndex() - 1))
        self.b_next = push("Next", "primary", icon_name="step_fwd")
        self.b_next.clicked.connect(lambda: self.go(self.stack.currentIndex() + 1))
        self.b_create = push("Create model", icon_name="model")
        self.b_create.clicked.connect(lambda: self._finish(False))
        self.b_run = push("Create && run", "run", icon_name="play")
        self.b_run.clicked.connect(lambda: self._finish(True))
        cancel = push("Cancel", "ghost")
        cancel.clicked.connect(self.reject)
        nav.addWidget(cancel)
        nav.addStretch()
        for b in (self.b_back, self.b_next, self.b_create, self.b_run):
            nav.addWidget(b)
        mv.addLayout(nav)
        root.addWidget(main, 1)
        self._build_case_page(start_case)
        self.go(0)

    # -- pages ----------------------------------------------------------------
    def _build_case_page(self, start_case):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 10, 0, 0)
        self.case_list = QListWidget()
        self.case_list.setIconSize(QSize(28, 28))
        self.case_list.setSpacing(3)
        for info in S.list_cases():
            ic, col = CASE_ICONS.get(info.module, ("model", "#64748b"))
            it = QListWidgetItem(icons.icon(ic, col, 28), f"{info.title}\n{info.summary}")
            it.setData(Qt.UserRole, info.module)
            it.setSizeHint(QSize(100, 62))
            self.case_list.addItem(it)
        row = 0
        if start_case:
            for i in range(self.case_list.count()):
                if self.case_list.item(i).data(Qt.UserRole) == start_case:
                    row = i
        self.case_list.setCurrentRow(row)
        self.case_list.itemDoubleClicked.connect(lambda _: self.go(1))
        v.addWidget(self.case_list)
        v.addWidget(label("Tip: choose the case closest to your experiment – its numerical settings are already "
                          "tuned. Gases without built-in equations automatically use the bundled BOLSIG+ and LXCat "
                          "tables.", "hint", wrap=True))
        self.stack.addWidget(w)
        for _ in STEPS[1:]:
            self.stack.addWidget(QWidget())

    def _ensure_model(self):
        mod = self.case_list.currentItem().data(Qt.UserRole)
        if self.model is None or self.model.base_case != mod:
            self.model = new_model_from_case(mod)
            self._built = set()
            self._forms = []

    def _form_page(self, idx, paths_or_group, preview_kind):
        """Form on the left, a live preview on the right."""
        old = self.stack.widget(idx)
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 10, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 10, 0)
        if isinstance(paths_or_group, str):
            form = SettingsForm(self.model, paths_or_group, compact=True)
        else:
            group = paths_or_group[0].rpartition(".")[0]
            form = SettingsForm(self.model, group, paths=paths_or_group, compact=True)
        form.changed.connect(lambda p, val, f=form: self._changed(p, val))
        form.reset_requested.connect(lambda p: (self.model.reset(p), self._refresh()))
        form.action.connect(self._action)
        il.addWidget(form)
        self._forms.append(form)
        extra = QVBoxLayout()
        il.addLayout(extra)
        il.addStretch()
        sc.setWidget(inner)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        h.addWidget(sc, 7)
        prev = QFrame()
        prev.setObjectName("cardFlat")
        pv = QVBoxLayout(prev)
        pv.setContentsMargins(8, 8, 8, 8)
        widget = None
        note = None
        if preview_kind == "paschen":
            widget = PlotCanvas("", height=300)
            note = label("", "muted", wrap=True)
        elif preview_kind == "wave":
            widget = PlotCanvas("", height=300)
        elif preview_kind == "circuit":
            widget = CircuitDiagram()
        elif preview_kind == "device":
            widget = DeviceSchematic()
        if widget is not None:
            pv.addWidget(widget, 1)
        if note is not None:
            pv.addWidget(note)
        h.addWidget(prev, 5)
        self.stack.removeWidget(old)
        old.deleteLater()
        self.stack.insertWidget(idx, w)
        return form, widget, note, extra

    def _build_page(self, idx):
        m = self.model
        if idx == 1:
            self.p1 = self._form_page(1, ["plasma_state.gas", "plasma_state.p_Torr", "plasma_state.T_i",
                                          "plasma_state.n0"], "paschen")
            g = SettingsForm(m, "geometry", compact=True)
            g.changed.connect(self._changed)
            self._forms.append(g)
            self.p1[3].addWidget(g)
        elif idx == 2:
            self.p2 = self._form_page(2, "waveform", "wave")
            rf = SettingsForm(m, "run", paths=["run.T_total"], compact=True)
            rf.changed.connect(self._changed)
            self._forms.append(rf)
            self.p2[3].addWidget(label("The simulated time window is set on the 'Duration' step; it is shown here "
                                       "because the waveform preview spans it.", "hint", wrap=True))
            self.p2[3].addWidget(rf)
        elif idx == 3:
            self.p3 = self._form_page(3, "circuit", "circuit")
        elif idx == 4:
            self.p4 = self._form_page(4, "emission", "device")
        elif idx == 5:
            self._build_resolution()
        elif idx == 6:
            self._build_review()

    def _build_resolution(self):
        old = self.stack.widget(5)
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 10, 0, 0)
        pres = QHBoxLayout()
        pres.addWidget(label("Presets:", "muted"))
        for name, tip, fn in (("Quick look", "Half the grid points and ¼ of the time steps (adaptive sub-stepping keeps"
                                             " it stable). Good for a first impression.", self._preset_quick),
                              ("Case default", "The tuned settings of the base case.", self._preset_default),
                              ("Fine", "Double grid points and time steps – for convergence checks.",
                               self._preset_fine)):
            b = push(name)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            pres.addWidget(b)
        pres.addStretch()
        v.addLayout(pres)
        h = QHBoxLayout()
        form = SettingsForm(self.model, "numerics", paths=["run.T_total", "numerics.Nx", "numerics.Nt",
                                                          "numerics.use_adaptive_substepping",
                                                          "numerics.hotloop_backend", "output.save_every",
                                                          "output.log_intermediate", "run.run_name"], compact=True)
        form.changed.connect(self._changed)
        self._forms.append(form)
        h.addWidget(form, 5)
        tiles = QGridLayout()
        self.r_tiles = {k: StatTile(t, "–", "", ic) for k, t, ic in
                        (("dt", "Time step dt", "clock"), ("dx", "Grid spacing dx", "grid"),
                         ("run", "Estimated run time", "cpu"), ("size", "Output size", "output"))}
        for i, t in enumerate(self.r_tiles.values()):
            tiles.addWidget(t, i // 2, i % 2)
        tw = QWidget()
        tw.setLayout(tiles)
        h.addWidget(tw, 4)
        v.addLayout(h)
        v.addWidget(label("Run time is a rough estimate that improves after your first runs on this computer.",
                          "hint"))
        v.addStretch()
        self.stack.removeWidget(old)
        old.deleteLater()
        self.stack.insertWidget(5, w)

    def _build_review(self):
        old = self.stack.widget(6)
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 10, 0, 0)
        g = QGridLayout()
        g.addWidget(label("Model title"), 0, 0)
        self.title_edit = QLineEdit(self.model.display_title())
        g.addWidget(self.title_edit, 0, 1)
        v.addLayout(g)
        self.review = label("", wrap=True, selectable=True)
        self.review.setTextFormat(Qt.RichText)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.addWidget(self.review)
        il.addStretch()
        sc.setWidget(inner)
        v.addWidget(sc, 1)
        self.stack.removeWidget(old)
        old.deleteLater()
        self.stack.insertWidget(6, w)

    # -- behaviour ----------------------------------------------------------------
    def go(self, idx):
        idx = max(0, min(len(STEPS) - 1, idx))
        if idx > 0:
            self._ensure_model()
            if idx not in self._built:
                self._build_page(idx)
                self._built.add(idx)
        self.stack.setCurrentIndex(idx)
        for i, b in enumerate(self.step_btns):
            b.setChecked(i == idx)
            b.setEnabled(i == 0 or self.model is not None or i <= idx)
        name = STEPS[idx][0]
        self.head.setText(name)
        self.headsub.setText({
            0: "Choose a validated PASCHEN-1D case as the starting point.",
            1: "Which gas, at what pressure, in what gap? The breakdown estimate tells you whether your voltage "
               "is likely to ignite a discharge.",
            2: "The source voltage V_app(t). With an external circuit the gap voltage will differ from it.",
            3: "The lumped circuit between the source and the plasma gap. The diagram updates as you type.",
            4: "Secondary emission and optional external emission (field, thermionic, constant or laser "
               "photoemission). Only the parameters of the mechanisms you switch on are shown.",
            5: "How long to simulate and how finely. Estimates update instantly.",
            6: "Name the model and review what you changed. You can still edit everything in the Model Builder.",
        }[idx])
        self.b_back.setEnabled(idx > 0)
        self.b_next.setVisible(idx < len(STEPS) - 1)
        self._refresh()

    def _changed(self, path, value):
        if self.model.set(path, value):
            if path == "plasma_state.gas" and not S.has_empirical_closures(str(value)):
                A.auto_configure_gas(self.model, str(value))
            self._refresh()

    def _action(self, name):
        if name == "auto_gas":
            A.auto_configure_gas(self.model, str(self.model.value("plasma_state.gas")))
            self._refresh()
        elif name == "ion_browser":
            from .dialogs import IonBrowserDialog
            dlg = IonBrowserDialog(self.model, self)
            if dlg.exec():
                dlg.apply_to(self.model)
                self._refresh()

    def _refresh(self):
        for f in self._forms:
            try:
                f.refresh()
            except RuntimeError:
                pass
        idx = self.stack.currentIndex()
        m = self.model
        if m is None:
            return
        try:
            if idx == 1:
                spec, note = paschen_spec(m)
                self.p1[1].set_spec(spec, keep_view=False)
                self.p1[2].setText(note)
            elif idx == 2:
                self.p2[1].set_spec(waveform_spec(m), keep_view=False)
            elif idx == 3:
                self.p3[1].set_values(m.values())
            elif idx == 4:
                self.p4[1].set_values(m.values())
            elif idx == 5:
                e = A.estimate(m)
                self.r_tiles["dt"].set(format_quantity(e["dt"], "s"), f"{e['Nt'] - 1:,} steps")
                self.r_tiles["dx"].set(format_quantity(e["dx"], "m"), f"{e['Nx']} grid points")
                self.r_tiles["run"].set(human_duration(e["runtime_s"]))
                self.r_tiles["size"].set(human_bytes(e["bytes_total"]), f"{e['nsave']:,} snapshots")
            elif idx == 6:
                self._review_text()
        except Exception as exc:  # pragma: no cover
            self.headsub.setText(f"Preview error: {exc}")

    def _review_text(self):
        m = self.model
        rows = m.summary_rows()
        issues = A.check_model(m, workspace=self.workspace, deep=True)
        col = {"error": T.c("danger"), "warning": T.c("warning"), "ok": T.c("success"), "info": T.c("text2")}
        html = [f"<p>Base case: <b>{m.base_case}</b></p>"]
        if rows:
            html.append("<p><b>Changed settings</b></p><table cellspacing=6>")
            for p, d, val in rows:
                fi = m.schema.fields[p]
                html.append(f"<tr><td>{SC.meta_for(p, fi.comment).label}</td><td style='color:gray'>{d}</td>"
                            f"<td>→</td><td><b>{val}</b></td></tr>")
            html.append("</table>")
        else:
            html.append("<p>No settings changed – the model equals the base case.</p>")
        html.append("<p><b>Model check</b></p>")
        for i in issues:
            html.append(f"<p style='color:{col.get(i.level)}'>● {i.message}</p>")
        self.review.setText("".join(html))

    def _preset_default(self):
        for p in ("numerics.Nx", "numerics.Nt", "output.save_every"):
            self.model.reset(p)
        self._refresh()

    def _preset_quick(self):
        d = self.model.defaults()
        Nx = max(100, int(d["numerics.Nx"]) // 2)
        Nt = max(2000, int(d["numerics.Nt"]) // 4)
        self.model.set("numerics.Nx", Nx)
        self.model.set("numerics.Nt", Nt)
        self.model.set("numerics.use_adaptive_substepping", True)
        self.model.set("output.save_every", max(1, (Nt - 1) // 500))
        self._refresh()

    def _preset_fine(self):
        d = self.model.defaults()
        Nt = int(d["numerics.Nt"]) * 2
        self.model.set("numerics.Nx", int(d["numerics.Nx"]) * 2)
        self.model.set("numerics.Nt", Nt)
        self.model.set("output.save_every", max(1, (Nt - 1) // 2000))
        self._refresh()

    def _finish(self, run: bool):
        self._ensure_model()
        if hasattr(self, "title_edit"):
            self.model.title = self.title_edit.text().strip() or self.model.title
        self.run_after = run
        self.accept()
