"""Parameter-sweep set-up dialog."""
from __future__ import annotations


from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLineEdit, QRadioButton,
                               QSpinBox, QVBoxLayout, QWidget)

from .. import schema as SC
from ..sweep import make_values
from ..units import format_quantity, parse_quantity
from .widgets import QuantityEdit, label


class SweepDialog(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.chosen = None
        self.setWindowTitle("Parameter sweep")
        self.setMinimumWidth(640)
        v = QVBoxLayout(self)
        v.addWidget(label("Parameter sweep", "h3"))
        v.addWidget(label("Runs the current model once per value of one setting. Each run gets its own folder; "
                          "the Results page groups them and plots any metric against the parameter "
                          "(e.g. peak current vs. applied voltage, or a breakdown scan vs. pressure).",
                          "muted", wrap=True))
        form = QFormLayout()
        self.param = QComboBox()
        self.param.setEditable(False)
        numeric = [p for p, fi in model.schema.fields.items() if fi.kind in ("float", "int")]
        pref = ["waveform.V_peak", "plasma_state.p_Torr", "geometry.L", "emission.gamma", "circuit.R0",
                "circuit.R_m", "circuit.C_ext", "plasma_state.n0", "numerics.Nx", "numerics.Nt"]
        ordered = [p for p in pref if p in numeric] + sorted(p for p in numeric if p not in pref)
        for p in ordered:
            fi = model.schema.fields[p]
            meta = SC.meta_for(p, fi.comment)
            g = p.rpartition(".")[0]
            self.param.addItem(f"{meta.label}  —  {SC.GROUP_TITLES.get(g, g)}", p)
        prev = (model.sweep or {}).get("parameter")
        if prev and self.param.findData(prev) >= 0:
            self.param.setCurrentIndex(self.param.findData(prev))
        self.param.currentIndexChanged.connect(self._param_changed)
        form.addRow("Parameter", self.param)
        self.cur = label("", "hint")
        form.addRow("", self.cur)
        mode = QHBoxLayout()
        self.r_range = QRadioButton("Range")
        self.r_list = QRadioButton("List of values")
        self.r_range.setChecked(True)
        mode.addWidget(self.r_range)
        mode.addWidget(self.r_list)
        mode.addStretch()
        form.addRow("Values", mode)
        rw = QWidget()
        rl = QHBoxLayout(rw)
        rl.setContentsMargins(0, 0, 0, 0)
        self.v0 = QuantityEdit("")
        self.v1 = QuantityEdit("")
        self.n = QSpinBox()
        self.n.setRange(2, 500)
        self.n.setValue(6)
        self.spacing = QComboBox()
        self.spacing.addItems(["linear", "logarithmic"])
        rl.addWidget(label("from"))
        rl.addWidget(self.v0)
        rl.addWidget(label("to"))
        rl.addWidget(self.v1)
        rl.addWidget(label("points"))
        rl.addWidget(self.n)
        rl.addWidget(self.spacing)
        form.addRow("", rw)
        self.list = QLineEdit()
        self.list.setPlaceholderText("e.g. 140, 160, 180, 200   (units and prefixes allowed)")
        form.addRow("", self.list)
        self.prefix = QLineEdit(f"{model.run_name}_sweep")
        form.addRow("Run-name prefix", self.prefix)
        self.conc = QSpinBox()
        self.conc.setRange(1, 64)
        self.conc.setValue(1)
        self.conc.setToolTip("Simultaneous runs (each uses one CPU core). Also changes the global setting.")
        form.addRow("Run at the same time", self.conc)
        v.addLayout(form)
        self.preview = label("", "derived", wrap=True)
        v.addWidget(self.preview)
        bb = QDialogButtonBox()
        self.ok = bb.addButton("Queue sweep runs", QDialogButtonBox.AcceptRole)
        self.ok.setObjectName("run")
        bb.addButton(QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        for w in (self.v0, self.v1):
            w.committed.connect(lambda _: self._update())
        self.n.valueChanged.connect(lambda _: self._update())
        self.spacing.currentIndexChanged.connect(lambda _: self._update())
        self.list.textChanged.connect(lambda _: self._update())
        self.r_range.toggled.connect(lambda _: self._update())
        self._param_changed()

    def _param_changed(self):
        p = self.param.currentData()
        fi = self.model.schema.fields[p]
        meta = SC.meta_for(p, fi.comment)
        cur = self.model.value(p)
        for w in (self.v0, self.v1):
            w.unit = meta.unit
            w.integer = fi.kind == "int"
        self.cur.setText(f"current value: {format_quantity(cur, meta.unit)}")
        try:
            c = float(cur)
            lo, hi = (0.5 * c, 1.5 * c) if c != 0 else (0.0, 1.0)
            if fi.kind == "int":
                lo, hi = int(round(lo)), int(round(hi))
            self.v0.setValue(lo)
            self.v1.setValue(hi)
        except (TypeError, ValueError):
            pass
        self._update()

    def values(self):
        p = self.param.currentData()
        fi = self.model.schema.fields[p]
        meta = SC.meta_for(p, fi.comment)
        if self.r_list.isChecked():
            vals = []
            for tok in self.list.text().replace(";", ",").split(","):
                if tok.strip():
                    vals.append(parse_quantity(tok, meta.unit))
        else:
            vals = make_values(self.v0.value(), self.v1.value(), self.n.value(),
                               "log" if self.spacing.currentIndex() == 1 else "linear")
        if fi.kind == "int":
            vals = sorted(set(int(round(x)) for x in vals))
        return vals

    def _update(self):
        try:
            vals = self.values()
            p = self.param.currentData()
            meta = SC.meta_for(p, self.model.schema.fields[p].comment)
            self.preview.setText(f"{len(vals)} runs:  " + ",  ".join(format_quantity(x, meta.unit) for x in vals[:30])
                                 + ("  …" if len(vals) > 30 else ""))
            self.ok.setEnabled(len(vals) > 0)
        except Exception as exc:
            self.preview.setText(f"⚠ {exc}")
            self.ok.setEnabled(False)

    def _accept(self):
        try:
            vals = self.values()
        except Exception:
            return
        p = self.param.currentData()
        self.chosen = dict(parameter=p, values=list(vals), prefix=self.prefix.text().strip() or "sweep",
                           concurrent=self.conc.value())
        self.accept()
