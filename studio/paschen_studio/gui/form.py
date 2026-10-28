"""Settings form generated from the solver's configuration schema."""
from __future__ import annotations

import ast
import math

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QToolButton, QVBoxLayout, QWidget)

from .. import advisor as A
from .. import schema as SC
from .. import solver as S
from ..units import format_quantity, human_bytes
from . import icons
from . import theme as T
from .widgets import ChoiceCombo, FlowLayout, QuantityEdit, SectionHeader, ToggleSwitch, label

INF_OK = {"circuit.C_s", "circuit.L_p"}


def _tooltip(path: str, fi, meta, default) -> str:
    parts = [f"<b>{meta.label}</b>"]
    if meta.hint:
        parts.append(meta.hint)
    if fi.comment:
        parts.append("<span style='white-space:pre-wrap'>" + fi.comment.replace("<", "&lt;") + "</span>")
    parts.append(f"<span style='color:gray'>cfg.{path} · {fi.type_repr} · case default: "
                 f"{format_quantity(default, meta.unit) if isinstance(default, float) else default!r}</span>")
    return "<br><br>".join(parts)


class FieldRow:
    """Label + editor + reset button for one configuration field."""

    def __init__(self, form: "SettingsForm", path: str):
        self.form = form
        self.path = path
        model = form.model
        self.fi = model.schema.fields[path]
        self.meta = SC.meta_for(path, self.fi.comment)
        default = model.default(path)
        tip = _tooltip(path, self.fi, self.meta, default)

        self.dot = QLabel()
        self.dot.setFixedWidth(10)
        self.dot.setPixmap(icons.pixmap("dot", T.c("accent"), 10))
        self.lab = QLabel(self.meta.label)
        self.lab.setToolTip(tip)
        self.lab.setWordWrap(True)
        self.lab.setMinimumWidth(150)
        self.editor = self._make_editor()
        self.editor.setToolTip(tip)
        self.reset = QToolButton()
        self.reset.setObjectName("reset")
        self.reset.setIcon(icons.icon("reset", T.c("text3"), 14))
        self.reset.setIconSize(QSize(14, 14))
        self.reset.setToolTip(f"Reset to the case default")
        self.reset.setCursor(Qt.PointingHandCursor)
        self.reset.clicked.connect(lambda: form.on_reset(path))
        self.help = QLabel()
        self.help.setPixmap(icons.pixmap("info", T.c("text3"), 14))
        self.help.setToolTip(tip)
        self.note = label("", "hint", wrap=True)
        self.note.setVisible(False)
        self.widgets = [self.dot, self.lab, self.editor_container, self.reset, self.help, self.note]

    # -- editors --------------------------------------------------------------
    def _make_editor(self):
        path, fi, meta = self.path, self.fi, self.meta
        model = self.form.model
        val = model.value(path)
        commit = lambda v: self.form.on_change(path, v)  # noqa: E731
        box = QWidget()
        hl = QHBoxLayout(box)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        self.editor_container = box
        ed: QWidget
        if path in SC.TABLE_FIELDS and SC.TABLE_FIELDS[path] == "electron":
            ed = QComboBox()
            ed.setEditable(True)
            ed.setInsertPolicy(QComboBox.NoInsert)
            self._fill_electron_tables(ed)
            ed.setCurrentText(str(val or ""))
            ed.activated.connect(lambda i, e=ed: commit(e.itemData(i) or e.currentText().strip()))
            ed.lineEdit().editingFinished.connect(lambda e=ed: self._commit_text(_combo_value(e)))
            hl.addWidget(ed, 1)
        elif path in SC.TABLE_FIELDS:
            ed = QLineEdit(str(val or ""))
            ed.setPlaceholderText("None")
            ed.editingFinished.connect(lambda e=ed: self._commit_text(e.text().strip() or None))
            hl.addWidget(ed, 1)
            b = QPushButton("Browse…")
            b.setToolTip("Browse the bundled LXCat ion transport library")
            b.clicked.connect(self.form.open_ion_browser)
            hl.addWidget(b)
        elif path == "plasma_state.gas":
            ed = QComboBox()
            ed.setEditable(True)
            ed.setInsertPolicy(QComboBox.NoInsert)
            for g, disp in S.known_gases():
                ed.addItem(disp, g)
            ed.setCurrentText(str(val))
            ed.activated.connect(lambda i, e=ed: commit(e.itemData(i) or e.currentText().strip()))
            ed.lineEdit().editingFinished.connect(lambda e=ed: self._commit_text(_combo_value(e)))
            hl.addWidget(ed, 1)
            b = QPushButton("Use bundled tables")
            b.setToolTip("Point electron and ion transport at the bundled BOLSIG+ / LXCat tables for this gas")
            b.clicked.connect(self.form.auto_gas)
            hl.addWidget(b)
        elif path == "ion_transport.positive_ion":
            ed = QLineEdit(str(val))
            ed.editingFinished.connect(lambda e=ed: self._commit_text(e.text().strip()))
            hl.addWidget(ed, 1)
            b = QPushButton("Ion library…")
            b.clicked.connect(self.form.open_ion_browser)
            hl.addWidget(b)
        elif path == "waveform.table_path":
            ed = QLineEdit(str(val))
            ed.editingFinished.connect(lambda e=ed: self._commit_text(e.text().strip()))
            hl.addWidget(ed, 1)
            b = QPushButton("Browse…")
            b.clicked.connect(lambda: self._browse_csv(ed))
            hl.addWidget(b)
        elif fi.kind == "bool":
            ed = ToggleSwitch(bool(val))
            ed.toggled.connect(lambda on: commit(bool(on)))
            hl.addWidget(ed)
            self.state_lab = label("On" if val else "Off", "muted")
            hl.addWidget(self.state_lab)
            hl.addStretch()
        elif fi.kind == "choice":
            ed = ChoiceCombo(fi.choices or [], SC.CHOICE_LABELS, val)
            ed.committed.connect(commit)
            hl.addWidget(ed, 1)
        elif fi.kind in ("float", "int", "optional_float"):
            ed = QuantityEdit(meta.unit, val, integer=(fi.kind == "int"), allow_inf=path in INF_OK,
                              allow_none=(fi.kind == "optional_float"), minimum=meta.minimum)
            ed.committed.connect(commit)
            hl.addWidget(ed, 1)
            if meta.unit:
                u = label(meta.unit, "faint")
                u.setMinimumWidth(34)
                hl.addWidget(u)
        elif fi.kind == "multichoice":
            ed = QWidget()
            fl = FlowLayout(ed, 10, 4)
            self._checks = {}
            cur = set(val or ())
            for ch in fi.choices or []:
                cb = QCheckBox(ch)
                cb.setChecked(ch in cur)
                cb.toggled.connect(lambda _=None: commit(tuple(c for c, w in self._checks.items() if w.isChecked())))
                fl.addWidget(cb)
                self._checks[ch] = cb
            hl.addWidget(ed, 1)
        elif fi.kind == "float_tuple_opt":
            ed = QLineEdit("" if val is None else ", ".join(f"{x:g}" for x in val))
            ed.setPlaceholderText("None (final snapshot)")
            ed.editingFinished.connect(lambda e=ed: self._commit_tuple(e))
            hl.addWidget(ed, 1)
        elif fi.kind == "python":
            ed = QLineEdit("" if val is None else repr(val))
            ed.setPlaceholderText("None")
            ed.editingFinished.connect(lambda e=ed: self._commit_python(e))
            hl.addWidget(ed, 1)
        else:  # str / optional_str
            ed = QLineEdit("" if val is None else str(val))
            if fi.kind == "optional_str":
                ed.setPlaceholderText("None")
            ed.editingFinished.connect(lambda e=ed: self._commit_text(
                (e.text().strip() or None) if fi.kind == "optional_str" else e.text().strip()))
            hl.addWidget(ed, 1)
        self.ed = ed
        return box

    def _fill_electron_tables(self, combo: QComboBox):
        gas_key = S.canonical_gas(str(self.form.model.value("plasma_state.gas")))
        tabs = S.electron_tables()
        tabs = sorted(tabs, key=lambda t: (str(t.get("canonical_gas", "")).lower() != gas_key, t.get("gas", "")))
        for t in tabs:
            rng = f"{t.get('common_e_over_n_min_Td', '?'):g}–{t.get('common_e_over_n_max_Td', '?'):g} Td" \
                if isinstance(t.get("common_e_over_n_min_Td"), (int, float)) else ""
            combo.addItem(f"{t['basename']}   ·  {t.get('gas', '')}  ·  {t.get('lxcat_database', '')}  ·  {rng}",
                          t["basename"])
        combo.setMinimumContentsLength(18)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)

    def _commit_text(self, v):
        if v is None or v != "" or self.fi.kind == "str":
            self.form.on_change(self.path, v)

    def _commit_tuple(self, e: QLineEdit):
        t = e.text().strip()
        if not t or t.lower() == "none":
            self.form.on_change(self.path, None)
            return
        try:
            from ..units import parse_quantity
            vals = tuple(parse_quantity(x, "s") for x in t.replace(";", ",").split(",") if x.strip())
            e.setProperty("invalid", False)
            self.form.on_change(self.path, vals)
        except Exception:
            e.setProperty("invalid", True)
        e.style().unpolish(e)
        e.style().polish(e)

    def _commit_python(self, e: QLineEdit):
        t = e.text().strip()
        try:
            v = None if not t or t == "None" else ast.literal_eval(t)
            e.setProperty("invalid", False)
            self.form.on_change(self.path, v)
        except Exception:
            e.setProperty("invalid", True)
        e.style().unpolish(e)
        e.style().polish(e)

    def _browse_csv(self, ed: QLineEdit):
        start = str(self.form.model.path.parent) if self.form.model.path else str(S.solver_root())
        p, _ = QFileDialog.getOpenFileName(self.form, "Voltage waveform table", start,
                                           "CSV files (*.csv *.txt *.dat);;All files (*)")
        if p:
            ed.setText(p)
            self._commit_text(p)

    # -- refresh --------------------------------------------------------------
    def set_value(self, v):
        ed = self.ed
        ed.blockSignals(True)
        try:
            if isinstance(ed, QuantityEdit):
                ed.setValue(v)
            elif isinstance(ed, ToggleSwitch):
                ed.setChecked(bool(v))
                self.state_lab.setText("On" if v else "Off")
            elif isinstance(ed, ChoiceCombo):
                ed.setValue(v)
            elif isinstance(ed, QComboBox):
                if not ed.lineEdit().hasFocus():
                    ed.setCurrentText("" if v is None else str(v))
            elif isinstance(ed, QLineEdit):
                if not ed.hasFocus():
                    if self.fi.kind == "python":
                        ed.setText("" if v is None else repr(v))
                    elif self.fi.kind == "float_tuple_opt":
                        ed.setText("" if v is None else ", ".join(f"{x:g}" for x in v))
                    else:
                        ed.setText("" if v is None else str(v))
            elif self.fi.kind == "multichoice":
                cur = set(v or ())
                for ch, cb in self._checks.items():
                    cb.blockSignals(True)
                    cb.setChecked(ch in cur)
                    cb.blockSignals(False)
        finally:
            ed.blockSignals(False)

    def refresh(self, values: dict, show_inactive: bool, show_advanced: bool) -> bool:
        model = self.form.model
        v = values.get(self.path)
        self.set_value(v)
        modified = model.is_modified(self.path)
        self.dot.setVisible(modified)
        self.reset.setVisible(modified)
        self.ed.setProperty("modified", modified)
        self.ed.style().unpolish(self.ed)
        self.ed.style().polish(self.ed)
        active, why = SC.field_active(self.path, values)
        derived = self.form.derived_text(self.path, values) if active else ""
        visible = (active or show_inactive) and (show_advanced or not self.meta.advanced or modified)
        self.editor_container.setEnabled(active)
        self.lab.setEnabled(active)
        note = derived if active else f"Not used: {why}"
        self.note.setText(note)
        self.note.setObjectName("derived" if active else "hint")
        self.note.style().unpolish(self.note)
        self.note.style().polish(self.note)
        for w in self.widgets:
            w.setVisible(visible)
        self.dot.setVisible(visible and modified)
        self.reset.setVisible(visible and modified)
        self.note.setVisible(visible and bool(note))
        return visible


# ---------------------------------------------------------------------------
class SettingsForm(QWidget):
    """All settings of one group, split into titled sections."""

    changed = Signal(str, object)
    reset_requested = Signal(str)
    action = Signal(str)                 # "auto_gas", "ion_browser"

    def __init__(self, model, group: str, paths: list[str] | None = None, parent=None,
                 show_inactive: bool = False, show_advanced: bool = False, compact: bool = False):
        super().__init__(parent)
        self.model = model
        self.group = group
        self.show_inactive = show_inactive
        self.show_advanced = show_advanced
        self.rows: dict[str, FieldRow] = {}
        self.sections = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        schema = model.schema
        if paths is None:
            g = schema.groups.get(group)
            paths = [f.path for f in g.fields] if g else []
        comments = {p: schema.fields[p].comment for p in paths if p in schema.fields}
        values = model.values()
        secs = SC.group_sections(group, [p for p in paths if p in schema.fields], values, comments)
        for sec in secs:
            hdr = SectionHeader(sec.title) if sec.title else None
            if hdr:
                outer.addWidget(hdr)
            gw = QWidget()
            grid = QGridLayout(gw)
            grid.setContentsMargins(0, 2, 0, 6)
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(3)
            grid.setColumnStretch(2, 1)
            grid.setColumnMinimumWidth(1, 200 if not compact else 190)
            r = 0
            rows = []
            for p in sec.paths:
                row = FieldRow(self, p)
                self.rows[p] = row
                rows.append(row)
                grid.addWidget(row.dot, r, 0, Qt.AlignVCenter)
                grid.addWidget(row.lab, r, 1, Qt.AlignVCenter)
                grid.addWidget(row.editor_container, r, 2)
                grid.addWidget(row.reset, r, 3)
                grid.addWidget(row.help, r, 4)
                grid.addWidget(row.note, r + 1, 2, 1, 3)
                r += 2
            outer.addWidget(gw)
            self.sections.append((hdr, gw, rows))
        self.empty = label("No settings are relevant for the current choices. Enable “Show inactive” to see them.",
                           "muted", wrap=True)
        outer.addWidget(self.empty)
        outer.addStretch(1)
        self.refresh()

    # callbacks from rows
    def on_change(self, path: str, value):
        self.changed.emit(path, value)

    def on_reset(self, path: str):
        self.reset_requested.emit(path)

    def auto_gas(self):
        self.action.emit("auto_gas")

    def open_ion_browser(self):
        self.action.emit("ion_browser")

    def set_flags(self, show_inactive: bool | None = None, show_advanced: bool | None = None):
        if show_inactive is not None:
            self.show_inactive = show_inactive
        if show_advanced is not None:
            self.show_advanced = show_advanced
        self.refresh()

    def refresh(self):
        values = self.model.values()
        any_vis = False
        self._est = None
        for hdr, gw, rows in self.sections:
            vis = False
            for row in rows:
                vis |= row.refresh(values, self.show_inactive, self.show_advanced)
            gw.setVisible(vis)
            if hdr:
                hdr.setVisible(vis)
            any_vis |= vis
        self.empty.setVisible(not any_vis)

    def focus_field(self, path: str):
        row = self.rows.get(path)
        if row is None:
            return None
        row.ed.setFocus()
        return row.editor_container

    # -- derived hints -----------------------------------------------------------
    def _estimate(self):
        if getattr(self, "_est", None) is None:
            self._est = A.estimate(self.model)
        return self._est

    def derived_text(self, path: str, v: dict) -> str:
        try:
            if path == "numerics.Nt":
                e = self._estimate()
                return f"dt = {format_quantity(e['dt'], 's')}  ·  ≈ {_dur(e['runtime_s'])} estimated run time"
            if path == "numerics.Nx":
                e = self._estimate()
                return f"dx = {format_quantity(e['dx'], 'm')}"
            if path == "run.T_total":
                e = self._estimate()
                return f"{e['Nt'] - 1:,} macro steps of {format_quantity(e['dt'], 's')}"
            if path == "output.save_every":
                e = self._estimate()
                return (f"≈ {e['nsave']:,} snapshots, one every {format_quantity(e['dt'] * e['save_every'], 's')}"
                        f"  ·  output ≈ {human_bytes(e['bytes_total'])}")
            if path == "plasma_state.p_Torr":
                e = self._estimate()
                return f"N = {e['neutral_density']:.3g} m⁻³  ·  pd = {e['pd_Torr_cm']:.3g} Torr·cm"
            if path == "geometry.L":
                e = self._estimate()
                C = 8.8541878128e-12 * float(v["geometry.A"]) / float(v["geometry.L"])
                return f"pd = {e['pd_Torr_cm']:.3g} Torr·cm  ·  C_gap = {format_quantity(C, 'F')}"
            if path == "geometry.A":
                return f"= {float(v['geometry.A']) * 1e4:.4g} cm²"
            if path == "waveform.V_peak":
                e = self._estimate()
                return (f"mean field {format_quantity(e['E_mean'], 'V/m')}  ·  E/N ≈ {e['E_over_N_Td']:.3g} Td")
            if path == "waveform.f_rf":
                return f"period {format_quantity(1.0 / float(v['waveform.f_rf']), 's')}"
            if path == "plasma_state.T_i":
                return f"{float(v['plasma_state.T_i']) * 8.617333e-5:.4g} eV"
            if path == "plasma_state.T_e":
                return f"{float(v['plasma_state.T_e']) * 8.617333e-5:.4g} eV"
            if path == "emission.gamma":
                g = float(v["emission.gamma"])
                return f"breakdown criterion ln(1 + 1/γ) = {math.log(1 + 1 / g):.3g}" if g > 0 else ""
        except Exception:
            return ""
        return ""


def _combo_value(combo: QComboBox):
    text = combo.currentText().strip()
    for i in range(combo.count()):
        if combo.itemText(i) == text:
            return combo.itemData(i)
    return text


def _dur(s):
    from ..units import human_duration
    return human_duration(s)
