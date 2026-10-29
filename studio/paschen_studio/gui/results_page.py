"""Results browser: every run folder, interactive plots, animation, comparison and sweeps."""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox,
                               QScrollArea, QSlider, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import schema as SC
from ..runs import METRIC_LABELS, RunData, discover, summary_metrics
from ..units import format_quantity, human_duration
from . import icons
from . import theme as T
from .builder import pane
from .plotting import AxesSpec, FigureSpec, PlotCanvas, Series
from .runplots import (CURRENTS, NUMERICS, SPATIAL_GROUPS, VOLTAGES, averaged_spec, compare_spec, history_spec,
                       profiles_spec, spacetime_spec, time_scale)
from .widgets import ElidedLabel, FlowLayout, QuantityEdit, StatTile, badge, icon_button, label, push


def _fmt_metric(key, val):
    if val is None or (isinstance(val, float) and not math.isfinite(val)):
        return "–"
    unit = METRIC_LABELS.get(key, ("", ""))[1]
    if unit == "m⁻³":
        return f"{val:.3g} m⁻³"
    if unit == "":
        return f"{val:.3g}"
    return format_quantity(val, unit, digits=4)


class CheckList(QWidget):
    """Compact list of checkable quantities."""

    changed = Signal()

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(0, 0, 0, 0)
        self.v.setSpacing(2)
        if title:
            self.v.addWidget(label(title.upper(), "sectionTitle"))
        self.boxes: dict[str, QCheckBox] = {}

    def set_items(self, items: list[tuple[str, str]], checked: set[str]):
        for cb in self.boxes.values():
            cb.deleteLater()
        self.boxes = {}
        for key, text in items:
            cb = QCheckBox(text)
            cb.setChecked(key in checked)
            cb.toggled.connect(lambda _=None: self.changed.emit())
            self.v.addWidget(cb)
            self.boxes[key] = cb

    def add_header(self, text):
        self.v.addWidget(label(text.upper(), "sectionTitle"))

    def checked(self) -> list[str]:
        return [k for k, cb in self.boxes.items() if cb.isChecked()]


# ---------------------------------------------------------------------------
class RunView(QWidget):
    loadModel = Signal(str)
    deleted = Signal()

    def __init__(self, page, parent=None):
        super().__init__(parent)
        self.page = page
        self.rd: RunData | None = None
        self.info = None
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(8)
        hdr = QHBoxLayout()
        self.bdg = badge("finished")
        hdr.addWidget(self.bdg)
        self.title = ElidedLabel("", mode=Qt.ElideRight)    # long run titles elide; full title in the tooltip
        self.title.setObjectName("h3")
        hdr.addWidget(self.title, 1)
        self.b_load = push("Open model in builder", icon_name="model")
        self.b_load.setToolTip("Load the exact settings of this run into the Model page")
        self.b_load.clicked.connect(self._load_model)
        self.b_folder = push("Show folder", icon_name="folder")
        self.b_folder.clicked.connect(lambda: self.info and QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.info.path))))
        self.b_csv = push("Export data…", icon_name="csv")
        self.b_csv.clicked.connect(self._export_all)
        self.b_del = icon_button("trash", "Delete this run folder", size=18)
        self.b_del.clicked.connect(self._delete)
        for b in (self.b_load, self.b_folder, self.b_csv, self.b_del):
            hdr.addWidget(b)
        self._text_buttons = [(b, b.text()) for b in (self.b_load, self.b_folder, self.b_csv)]
        for b, t in self._text_buttons:
            if not b.toolTip():
                b.setToolTip(t.replace("&&", "&"))
        self._compact = None
        v.addLayout(hdr)
        self.sub = label("", "hint", selectable=True)
        v.addWidget(self.sub)
        self.tabs = QTabWidget()
        v.addWidget(self.tabs, 1)
        self._build_summary()
        self._build_histories()
        self._build_profiles()
        self._build_spacetime()
        self._build_average()
        self._build_meta()
        self.tabs.currentChanged.connect(lambda _: self._render_current())
        self._play = QTimer(self)
        self._play.timeout.connect(self._advance)

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        compact = self.width() < 1000          # narrow window: icon-only buttons, tabs without icons
        if compact == self._compact:
            return
        self._compact = compact
        for b, t in self._text_buttons:
            b.setText("" if compact else t)
        if not hasattr(self, "_tab_icons"):
            self._tab_icons = [self.tabs.tabIcon(i) for i in range(self.tabs.count())]
        for i, ic in enumerate(self._tab_icons):
            self.tabs.setTabIcon(i, QIcon() if compact else ic)

    # -- tabs -----------------------------------------------------------------
    def _build_summary(self):
        w = QWidget()
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(w)
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 10, 4, 4)
        self.tiles = {}
        grid = QGridLayout()
        grid.setSpacing(8)
        keys = ["I_peak_A", "t_I_peak_s", "charge_C", "V_gap_min_V", "V_gap_final_V", "ne_max_m3",
                "elapsed", "grid", "cfl_max"]
        titles = {"elapsed": ("Run time", "clock"), "grid": ("Grid / steps", "grid")}
        for i, k in enumerate(keys):
            t = StatTile(titles.get(k, (METRIC_LABELS.get(k, (k,))[0], None))[0], "–", "",
                         titles.get(k, (None, "chart"))[1])
            self.tiles[k] = t
            grid.addWidget(t, i // 3, i % 3)
        v.addLayout(grid)
        self.health_lab = label("", wrap=True)
        self.health_lab.setStyleSheet(f"background: {T.c('danger_soft')}; color: {T.c('danger')}; "
                                      "border-radius: 8px; padding: 8px 12px; font-weight: 600;")
        self.health_lab.hide()
        v.addWidget(self.health_lab)
        self.info_lab = label("", "muted", wrap=True, selectable=True)
        v.addWidget(self.info_lab)
        pg = QGridLayout()
        pg.setSpacing(10)
        self.sum_plots = [PlotCanvas("", height=220, export_name=n) for n in
                          ("voltages", "current", "densities", "ne_spacetime")]
        for i, p in enumerate(self.sum_plots):
            pg.addWidget(p, i // 2, i % 2)
        v.addLayout(pg)
        self.tabs.addTab(sc, icons.icon("chart", T.c("text2"), 16), "Summary")

    def _build_histories(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 8, 0, 0)
        side = QWidget()
        side.setFixedWidth(220)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(4, 0, 4, 0)
        self.h_checks = CheckList("Quantities")
        self.h_checks.changed.connect(self._render_histories)
        sv.addWidget(self.h_checks)
        sv.addSpacing(8)
        sv.addWidget(label("TIME WINDOW", "sectionTitle"))
        self.h_t0 = QuantityEdit("s", None, allow_none=True)
        self.h_t1 = QuantityEdit("s", None, allow_none=True)
        self.h_t0.setPlaceholderText("start (empty = 0)")
        self.h_t1.setPlaceholderText("end (empty = all)")
        self.h_t0.committed.connect(lambda _: self._render_histories())
        self.h_t1.committed.connect(lambda _: self._render_histories())
        sv.addWidget(self.h_t0)
        sv.addWidget(self.h_t1)
        sv.addStretch()
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(side)
        sc.setFixedWidth(240)
        h.addWidget(sc)
        self.h_plot = PlotCanvas("", export_name="histories")
        h.addWidget(self.h_plot, 1)
        self.tabs.addTab(w, icons.icon("results", T.c("text2"), 16), "Time histories")

    def _build_profiles(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 8, 0, 0)
        top_w = QWidget()
        top = FlowLayout(top_w, 14, 6)            # wraps onto a second line in narrow windows
        self.p_group = {}
        for title, qs, _, _ in SPATIAL_GROUPS:
            cb = QCheckBox(title)
            cb.setChecked(title in ("Densities", "Electric field"))
            cb.toggled.connect(lambda _=None: self._render_profiles())
            self.p_group[title] = (cb, qs)
            top.addWidget(cb)
        self.p_xunit = QComboBox()
        self.p_xunit.addItems(["auto", "mm", "cm", "m", "µm"])
        self.p_xunit.currentIndexChanged.connect(lambda _: self._render_profiles())
        xw = QWidget()
        xl = QHBoxLayout(xw)
        xl.setContentsMargins(0, 0, 0, 0)
        xl.setSpacing(6)
        xl.addWidget(label("x unit"))
        xl.addWidget(self.p_xunit)
        top.addWidget(xw)
        self.p_lin = QCheckBox("Linear densities")
        self.p_lin.toggled.connect(lambda _: self._render_profiles())
        top.addWidget(self.p_lin)
        v.addWidget(top_w)
        ctl = QHBoxLayout()
        self.b_play = icon_button("play", "Play / pause the animation", size=18)
        self.b_play.clicked.connect(self._toggle_play)
        self.b_prev = icon_button("step_back", "Previous snapshot", size=18)
        self.b_next = icon_button("step_fwd", "Next snapshot", size=18)
        self.b_prev.clicked.connect(lambda: self.slider.setValue(self.slider.value() - 1))
        self.b_next.clicked.connect(lambda: self.slider.setValue(self.slider.value() + 1))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.valueChanged.connect(self._slider)
        self.t_lab = label("", "derived")
        self.t_lab.setMinimumWidth(200)
        self.speed = QComboBox()
        self.speed.addItems(["0.5×", "1×", "2×", "4×", "8×"])
        self.speed.setCurrentIndex(1)
        self.overlay = QCheckBox("Overlay 6 times")
        self.overlay.setToolTip("Draw six evenly spaced snapshots on top of each other")
        self.overlay.toggled.connect(lambda _: self._render_profiles())
        for wdg in (self.b_play, self.b_prev, self.b_next):
            ctl.addWidget(wdg)
        ctl.addWidget(self.slider, 1)
        ctl.addWidget(self.t_lab)
        ctl.addWidget(self.speed)
        ctl.addWidget(self.overlay)
        v.addLayout(ctl)
        self.p_plot = PlotCanvas("", export_name="profiles")
        v.addWidget(self.p_plot, 1)
        self.tabs.addTab(w, icons.icon("profile", T.c("text2"), 16), "Profiles")

    def _build_spacetime(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 8, 0, 0)
        top = QHBoxLayout()
        self.st_q = QComboBox()
        self.st_q.setMinimumContentsLength(20)
        self.st_q.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.st_q.currentIndexChanged.connect(lambda _: self._render_spacetime())
        self.st_log = QCheckBox("Logarithmic colour scale")
        self.st_log.setChecked(True)
        self.st_log.toggled.connect(lambda _: self._render_spacetime())
        self.st_cmap = QComboBox()
        self.st_cmap.addItems(["inferno", "viridis", "magma", "plasma", "cividis", "turbo", "RdBu_r", "coolwarm"])
        self.st_cmap.currentIndexChanged.connect(lambda _: self._render_spacetime())
        top.addWidget(label("Quantity"))
        top.addWidget(self.st_q)
        top.addWidget(self.st_log)
        top.addWidget(label("Colours"))
        top.addWidget(self.st_cmap)
        tip = label("Click the map to open that instant in Profiles", "hint", wrap=True)
        tip.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(tip, 1)
        v.addLayout(top)
        self.st_plot = PlotCanvas("", export_name="spacetime", log_toggle=False)
        self.st_plot.clicked.connect(self._st_click)
        v.addWidget(self.st_plot, 1)
        self.tabs.addTab(w, icons.icon("map", T.c("text2"), 16), "Space–time map")

    def _build_average(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 8, 0, 0)
        top = QHBoxLayout()
        self.a_group = {}
        for title, qs, _, _ in SPATIAL_GROUPS[:4]:
            cb = QCheckBox(title)
            cb.setChecked(title in ("Densities", "Potential"))
            cb.toggled.connect(lambda _=None: self._render_average())
            self.a_group[title] = (cb, qs)
            top.addWidget(cb)
        top.addSpacing(16)
        top.addWidget(label("from"))
        self.a_t0 = QuantityEdit("s", 0.0)
        self.a_t1 = QuantityEdit("s", 0.0)
        for q in (self.a_t0, self.a_t1):
            q.setMaximumWidth(140)
            q.committed.connect(lambda _: self._render_average())
        top.addWidget(self.a_t0)
        top.addWidget(label("to"))
        top.addWidget(self.a_t1)
        top.addStretch()
        v.addLayout(top)
        self.a_plot = PlotCanvas("", export_name="time_averaged")
        v.addWidget(self.a_plot, 1)
        self.tabs.addTab(w, icons.icon("layers", T.c("text2"), 16), "Time-averaged")

    def _build_meta(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 8, 0, 0)
        self.meta_tree = QTreeWidget()
        self.meta_tree.setHeaderLabels(["Key", "Value"])
        self.meta_tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.meta_tree.setAlternatingRowColors(True)
        v.addWidget(self.meta_tree, 1)
        self.tabs.addTab(w, icons.icon("info", T.c("text2"), 16), "Metadata")

    # -- loading -----------------------------------------------------------------
    def set_run(self, info):
        self._play.stop()
        self.info = info
        try:
            self.rd = RunData.open(info.path)
        except Exception as exc:
            self.rd = None
            self.title.setText(info.name)
            self.sub.setText(f"Cannot open this run: {exc}")
            return
        rd = self.rd
        self.title.setText(info.title)
        self.bdg.setText(info.status.capitalize())
        self.bdg.setObjectName(f"badge_{info.status}")
        self.bdg.style().unpolish(self.bdg)
        self.bdg.style().polish(self.bdg)
        st = info.studio or {}
        self.sub.setText(f"{info.path}   ·   {'Studio run' if info.source == 'studio' else 'notebook / script run'}"
                         + (f"   ·   case {st.get('base_case')}" if st.get("base_case") else ""))
        self.b_load.setEnabled((info.path / "studio_model.p1d.json").exists())
        # histories checklist
        avail = rd.available_temporal()
        items = [(q, SC.quantity_label(q)) for q in avail]
        default = {"V_app", "V_gap", "I_discharge"} & set(avail)
        self.h_checks.set_items(items, default)
        # profiles
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(rd.nsave_valid - 1, 0))
        self.slider.setValue(max(rd.nsave_valid - 1, 0))
        self.slider.blockSignals(False)
        sp = rd.available_spatial()
        for title, (cb, qs) in self.p_group.items():
            cb.setEnabled(any(q in sp for q in qs))
        self.st_q.blockSignals(True)
        self.st_q.clear()
        for q in sp:
            self.st_q.addItem(SC.quantity_label(q), q)
        self.st_q.blockSignals(False)
        tsc = rd.snapshot_times()
        if tsc.size:
            self.a_t0.setValue(float(tsc[len(tsc) // 2]))
            self.a_t1.setValue(float(tsc[-1]))
        self._fill_meta()
        self._summary()
        self._dirty = set(range(self.tabs.count()))
        self._render_current()

    def _fill_meta(self):
        self.meta_tree.clear()
        info = self.info

        def add(parent, key, val):
            it = QTreeWidgetItem([str(key), "" if isinstance(val, (dict, list)) else str(val)])
            if isinstance(val, dict):
                for k, vv in val.items():
                    add(it, k, vv)
            elif isinstance(val, list) and len(val) < 200:
                for i, vv in enumerate(val):
                    add(it, i, vv)
            if parent is None:
                self.meta_tree.addTopLevelItem(it)
            else:
                parent.addChild(it)
            return it

        if info.meta:
            top = add(None, "run_metadata.json", info.meta)
            top.setExpanded(True)
        if info.studio:
            add(None, "studio_run.json", {k: v for k, v in info.studio.items() if k != "config"})
            add(None, "full configuration", info.studio.get("config", {}))
        p = info.path / "surface_emission_charge_stats.json"
        if p.exists():
            try:
                add(None, p.name, json.loads(p.read_text()))
            except Exception:
                pass

    def _summary(self):
        rd, info = self.rd, self.info
        st = info.studio or {}
        metrics = st.get("summary") or {}
        if not metrics or "error" in metrics:
            try:
                metrics = summary_metrics(rd)
            except Exception:
                metrics = {}
        for k, t in self.tiles.items():
            if k == "elapsed":
                el = st.get("elapsed")
                t.set(human_duration(el) if el else "–", f"{st.get('rate', 0) or 0:,.0f} steps/s" if st.get("rate") else "")
            elif k == "grid":
                t.set(f"{rd.Nx} × {rd.Nt - 1:,}", f"dx = {format_quantity(rd.L / (rd.Nx - 1), 'm')} · "
                                                  f"dt = {format_quantity(rd.dt, 's')}")
            else:
                t.set(_fmt_metric(k, metrics.get(k)))
        try:
            from ..runs import health, health_message
            msg = health_message(health(rd))
        except Exception:
            msg = ""
        self.health_lab.setText("⚠ " + msg if msg else "")
        self.health_lab.setVisible(bool(msg))
        m = info.meta or {}
        cfg = st.get("config") or {}
        gas = m.get("gas", cfg.get("plasma_state.gas", "?"))
        p = m.get("p_Torr", cfg.get("plasma_state.p_Torr", float("nan")))
        wt = m.get("waveform_type", cfg.get("waveform.waveform_type", "?"))
        Vp = m.get("V_peak", cfg.get("waveform.V_peak", float("nan")))
        txt = (f"<b>{str(gas).capitalize()}</b> at {float(p):.4g} Torr · gap {format_quantity(rd.L, 'm')} · "
               f"{SC.choice_label(wt)} {format_quantity(float(Vp), 'V')} · simulated "
               f"{format_quantity(rd.t_valid(), 's')} of {format_quantity(rd.T_total, 's')} · "
               f"{rd.nsave_valid:,} snapshots")
        sw = (m.get("software") or {})
        if sw:
            txt += f"<br><span style='color:gray'>PASCHEN-1D {sw.get('paschen_1d_version', sw.get('version', ''))}"
            txt += f" · Python {sw.get('python', st.get('python', ''))}</span>"
        self.info_lab.setText(txt)

    # -- rendering ----------------------------------------------------------------
    def _render_current(self):
        if self.rd is None:
            return
        i = self.tabs.currentIndex()
        if i not in getattr(self, "_dirty", set()):
            return
        self._dirty.discard(i)
        try:
            [self._render_summary, self._render_histories, self._render_profiles, self._render_spacetime,
             self._render_average, lambda: None][i]()
        except Exception as exc:
            self.sub.setText(f"Plot error: {exc}")

    def _render_summary(self):
        rd = self.rd
        av = rd.available_temporal()
        self.sum_plots[0].set_spec(history_spec(rd, [q for q in ("V_app", "V_node", "V_gap") if q in av]),
                                   keep_view=False)
        self.sum_plots[1].set_spec(history_spec(rd, [q for q in ("I_discharge",) if q in av]), keep_view=False)
        k = rd.nsave_valid - 1
        spec = profiles_spec(rd, k, ["ne", "ni"])
        tsc, tu = time_scale(rd.T_total)
        if spec.axes:
            spec.axes[0].title = f"Final densities (t = {rd.snapshot_times()[-1] / tsc:.4g} {tu})"
        self.sum_plots[2].set_spec(spec, keep_view=False)
        if "ne" in rd.available_spatial():
            self.sum_plots[3].set_spec(spacetime_spec(rd, "ne", log=True), keep_view=False)

    def _render_histories(self):
        if self.rd is None:
            return
        qs = self.h_checks.checked()
        self.h_plot.set_spec(history_spec(self.rd, qs, self.h_t0.value(), self.h_t1.value(), max_points=8000),
                             keep_view=False)

    def _profile_quantities(self):
        qs = []
        for cb, q in self.p_group.values():
            if cb.isChecked():
                qs += q
        return qs

    def _render_profiles(self, keep=False):
        rd = self.rd
        if rd is None:
            return
        k = self.slider.value()
        times = rd.snapshot_times()
        tsc, tu = time_scale(rd.T_total)
        overlay = None
        if self.overlay.isChecked() and rd.nsave_valid > 1:
            overlay = sorted(set(np.linspace(0, rd.nsave_valid - 1, 6).astype(int).tolist()))
            self.t_lab.setText(f"{len(overlay)} snapshots")
        else:
            self.t_lab.setText(f"t = {times[min(k, len(times) - 1)] / tsc:.5g} {tu}   ({k + 1}/{rd.nsave_valid})")
        spec = profiles_spec(rd, k, self._profile_quantities(), x_unit=self.p_xunit.currentText(),
                             log_density=not self.p_lin.isChecked(), overlay=overlay)
        self.p_plot.set_spec(spec, keep_view=keep)

    def _slider(self, k):
        if self.tabs.currentIndex() == 2:
            self._render_profiles(keep=True)
        else:
            self._dirty.add(2)

    def _toggle_play(self):
        if self._play.isActive():
            self._play.stop()
            self.b_play.setIcon(icons.icon("play", T.c("text2"), 18))
            return
        if self.slider.value() >= self.slider.maximum():
            self.slider.setValue(0)
        f = [0.5, 1, 2, 4, 8][self.speed.currentIndex()]
        self._play.start(int(80 / f))
        self.b_play.setIcon(icons.icon("pause", T.c("text2"), 18))

    def _advance(self):
        n = self.rd.nsave_valid if self.rd else 1
        step = max(1, n // 300)
        if self.slider.value() + step > self.slider.maximum():
            self._toggle_play()
            return
        self.slider.setValue(self.slider.value() + step)

    def _render_spacetime(self):
        rd = self.rd
        q = self.st_q.currentData()
        if rd is None or q is None:
            self.st_plot.clear("No spatial snapshots")
            return
        times = rd.snapshot_times()
        self.st_plot.set_spec(spacetime_spec(rd, q, log=self.st_log.isChecked(), cmap=self.st_cmap.currentText(),
                                             mark_t=float(times[min(self.slider.value(), len(times) - 1)])),
                              keep_view=False)

    def _st_click(self, x, y):
        rd = self.rd
        if rd is None:
            return
        tsc, _ = time_scale(rd.T_total)
        k = rd.nearest_snapshot(y * tsc)
        self.slider.setValue(k)
        self.tabs.setCurrentIndex(2)
        self._render_profiles()

    def _render_average(self):
        rd = self.rd
        if rd is None:
            return
        qs = []
        for cb, q in self.a_group.values():
            if cb.isChecked():
                qs += q
        t0 = self.a_t0.value() or 0.0
        t1 = self.a_t1.value() or rd.t_valid()
        self.a_plot.set_spec(averaged_spec(rd, qs, t0, t1), keep_view=False)

    # -- actions ----------------------------------------------------------------
    def _load_model(self):
        if self.info:
            self.loadModel.emit(str(self.info.path / "studio_model.p1d.json"))

    def _export_all(self):
        rd = self.rd
        if rd is None:
            return
        d = QFileDialog.getExistingDirectory(self, "Export run data to folder", str(self.info.path))
        if not d:
            return
        out = Path(d)
        import csv
        hist = rd.available_temporal()
        cols = {}
        for q in hist:
            t, y = rd.temporal(q, max_points=20000)
            cols[q] = (t, y)
        with open(out / f"{rd.run_dir.name}_histories.csv", "w", newline="") as f:
            w = csv.writer(f)
            names = list(cols)
            t0 = cols[names[0]][0] if names else []
            w.writerow(["time_s"] + names)
            for i in range(len(t0)):
                w.writerow([f"{t0[i]:.9g}"] + [f"{cols[n][1][i]:.9g}" if i < len(cols[n][1]) else "" for n in names])
        k = rd.nsave_valid - 1
        with open(out / f"{rd.run_dir.name}_final_profiles.csv", "w", newline="") as f:
            w = csv.writer(f)
            sp = rd.available_spatial()
            w.writerow(["x_m"] + sp)
            arrs = [rd.spatial(q, k) for q in sp]
            for i, x in enumerate(rd.x):
                w.writerow([f"{x:.9g}"] + [f"{a[i]:.9g}" for a in arrs])
        QMessageBox.information(self, "Export", f"Wrote histories and final profiles to\n{out}")

    def _delete(self):
        info = self.info
        if info is None:
            return
        if info.status in ("running", "paused"):
            QMessageBox.warning(self, "Delete run", "This run is still in progress.")
            return
        r = QMessageBox.question(self, "Delete run", f"Delete the run folder?\n\n{info.path}\n\nThis cannot be undone.")
        if r != QMessageBox.Yes:
            return
        try:
            shutil.rmtree(info.path)
        except OSError as exc:
            QMessageBox.critical(self, "Delete run", str(exc))
            return
        self.deleted.emit()

    def restyle(self):
        for c in self.sum_plots + [self.h_plot, self.p_plot, self.st_plot, self.a_plot]:
            c.restyle()
        self._dirty = set(range(self.tabs.count()))
        self._render_current()


# ---------------------------------------------------------------------------
class CompareView(QWidget):
    def __init__(self, page, parent=None):
        super().__init__(parent)
        self.page = page
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.addWidget(label("Compare runs", "h3"))
        v.addWidget(label("Tick runs in the list on the left (checkboxes), then choose what to overlay.", "muted"))
        top = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItem("Time history", "temporal")
        self.kind.addItem("Final profile", "spatial")
        self.q = QComboBox()
        self.norm = QCheckBox("Normalize")
        self.log = QCheckBox("Log y")
        for w in (self.kind, self.q):
            w.currentIndexChanged.connect(lambda _: self.render())
        self.norm.toggled.connect(lambda _: self.render())
        self.log.toggled.connect(lambda _: self.render())
        self.kind.currentIndexChanged.connect(lambda _: self._fill_q())
        top.addWidget(self.kind)
        top.addWidget(self.q)
        top.addWidget(self.norm)
        top.addWidget(self.log)
        top.addStretch()
        v.addLayout(top)
        self.plot = PlotCanvas("", export_name="comparison", log_toggle=False)
        v.addWidget(self.plot, 1)
        self._fill_q()

    def _fill_q(self):
        self.q.blockSignals(True)
        self.q.clear()
        if self.kind.currentData() == "temporal":
            for q in VOLTAGES + CURRENTS + NUMERICS:
                self.q.addItem(SC.quantity_label(q), q)
            self.q.setCurrentIndex(self.q.findData("I_discharge"))
        else:
            for _, qs, _, _ in SPATIAL_GROUPS:
                for q in qs:
                    self.q.addItem(SC.quantity_label(q), q)
        self.q.blockSignals(False)
        self.render()

    def render(self):
        runs = []
        for info in self.page.checked_runs():
            try:
                runs.append((info.title, RunData.open(info.path)))
            except Exception:
                pass
        self.plot.set_spec(compare_spec(runs, self.q.currentData() or "I_discharge", self.norm.isChecked(),
                                        self.kind.currentData(), self.log.isChecked()), keep_view=False)


# ---------------------------------------------------------------------------
class SweepView(QWidget):
    def __init__(self, page, parent=None):
        super().__init__(parent)
        self.page = page
        self.runs = []
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        self.title = label("", "h3")
        v.addWidget(self.title)
        self.sub = label("", "muted")
        v.addWidget(self.sub)
        sp = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        sp.addWidget(self.table)
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 6, 0, 0)
        top = QHBoxLayout()
        self.metric_combo = QComboBox()
        for k, (lab, _) in METRIC_LABELS.items():
            self.metric_combo.addItem(lab, k)
        self.metric_combo.setCurrentIndex(self.metric_combo.findData("I_peak_A"))
        self.metric_combo.currentIndexChanged.connect(lambda _: self.render())
        self.overlay_q = QComboBox()
        for q in ("V_gap", "I_discharge", "V_node"):
            self.overlay_q.addItem(SC.quantity_label(q), q)
        self.overlay_q.currentIndexChanged.connect(lambda _: self.render())
        self.logx = QCheckBox("log x")
        self.logx.toggled.connect(lambda _: self.render())
        top.addWidget(label("Metric"))
        top.addWidget(self.metric_combo)
        top.addWidget(self.logx)
        top.addSpacing(20)
        top.addWidget(label("Overlay"))
        top.addWidget(self.overlay_q)
        top.addStretch()
        bl.addLayout(top)
        h = QHBoxLayout()
        self.p_metric = PlotCanvas("", export_name="sweep_metric")
        self.p_overlay = PlotCanvas("", export_name="sweep_overlay")
        h.addWidget(self.p_metric)
        h.addWidget(self.p_overlay)
        bl.addLayout(h, 1)
        sp.addWidget(bottom)
        sp.setSizes([200, 500])
        v.addWidget(sp, 1)

    def set_sweep(self, sid: str, runs):
        self.runs = sorted(runs, key=lambda r: (r.studio or {}).get("sweep", {}).get("index", 0))
        sw = (self.runs[0].studio or {}).get("sweep", {}) if self.runs else {}
        self.param = sw.get("parameter", "?")
        self.title.setText(f"Sweep: {sw.get('label') or self.param}")
        done = sum(1 for r in self.runs if r.status == "finished")
        self.sub.setText(f"{len(self.runs)} runs ({done} finished) · parameter {self.param}")
        keys = list(METRIC_LABELS)
        self.table.setColumnCount(3 + len(keys))
        self.table.setHorizontalHeaderLabels([self.param.split(".")[-1], "Run", "Status"] +
                                             [METRIC_LABELS[k][0] for k in keys])
        self.table.setRowCount(len(self.runs))
        self._metrics = []
        for i, r in enumerate(self.runs):
            st = r.studio or {}
            met = st.get("summary") or {}
            if not met and r.status in ("finished", "stopped"):
                try:
                    met = summary_metrics(RunData.open(r.path))
                except Exception:
                    met = {}
            self._metrics.append(met)
            val = st.get("sweep", {}).get("value")
            self.table.setItem(i, 0, QTableWidgetItem(self._fmt_val(val)))
            self.table.setItem(i, 1, QTableWidgetItem(r.name))
            self.table.setItem(i, 2, QTableWidgetItem(r.status))
            for j, k in enumerate(keys):
                self.table.setItem(i, 3 + j, QTableWidgetItem(_fmt_metric(k, met.get(k))))
        self.table.resizeColumnsToContents()
        self.render()

    def _fmt_val(self, val):
        try:
            unit = SC.meta_for(self.param).unit
            return format_quantity(float(val), unit) if unit else f"{float(val):g}"
        except (TypeError, ValueError):
            return str(val)

    def render(self):
        k = self.metric_combo.currentData()
        xs, ys = [], []
        for r, met in zip(self.runs, self._metrics if hasattr(self, "_metrics") else []):
            val = (r.studio or {}).get("sweep", {}).get("value")
            if val is None or met.get(k) is None:
                continue
            try:
                xs.append(float(val))
                ys.append(float(met[k]))
            except (TypeError, ValueError):
                pass
        unit = METRIC_LABELS.get(k, ("", ""))[1]
        big = max((abs(y) for y in ys if math.isfinite(y)), default=0.0)
        if big > 0 and unit in ("A", "s", "C", "V"):     # engineering prefix instead of a ×10⁻⁵ axis offset
            for pre, sc in (("p", 1e-12), ("n", 1e-9), ("µ", 1e-6), ("m", 1e-3), ("", 1.0), ("k", 1e3), ("M", 1e6)):
                if big < 1000 * sc or pre == "M":
                    break
            ys = [y / sc for y in ys]
            unit = pre + unit
        ax = AxesSpec(title=f"{METRIC_LABELS.get(k, (k,))[0]} vs {self.param.split('.')[-1]}",
                      xlabel=SC.meta_for(self.param).label + (f" [{SC.meta_for(self.param).unit}]" if SC.meta_for(self.param).unit else ""), ylabel=f"{METRIC_LABELS.get(k, (k,))[0]}" + (f" [{unit}]" if unit else ""),
                      xscale="log" if self.logx.isChecked() else "linear", legend=False)
        if xs:
            o = np.argsort(xs)
            ax.series.append(Series(np.array(xs)[o], np.array(ys)[o], marker="o", color=T.c("accent"), width=2))
        else:
            ax.empty_text = "Metrics appear as the sweep runs finish"
        self.p_metric.set_spec(FigureSpec([ax]), keep_view=False)
        q = self.overlay_q.currentData()
        runs = []
        for r in self.runs:
            if r.status not in ("finished", "stopped"):
                continue
            try:
                val = (r.studio or {}).get("sweep", {}).get("value")
                runs.append((f"{self.param.split('.')[-1]} = {self._fmt_val(val)}", RunData.open(r.path)))
            except Exception:
                pass
        self.p_overlay.set_spec(compare_spec(runs, q), keep_view=False)


# ---------------------------------------------------------------------------
class ResultsPage(QWidget):
    loadModel = Signal(str)

    def __init__(self, settings, folders_fn, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.folders_fn = folders_fn
        self.infos = []
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        sp = QSplitter(Qt.Horizontal)
        sp.setChildrenCollapsible(False)
        root.addWidget(sp)
        left, lv, lh, _ = pane("Results")
        b_ref = icon_button("refresh", "Rescan the result folders", size=16)
        b_ref.clicked.connect(self.refresh)
        b_add = icon_button("folder", "Add a folder that contains run folders…", size=16)
        b_add.clicked.connect(self._add_folder)
        lh.addWidget(b_add)
        lh.addWidget(b_ref)
        sw = QWidget()
        sl = QVBoxLayout(sw)
        sl.setContentsMargins(10, 8, 10, 4)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter runs…")
        self.search.addAction(icons.icon("search", T.c("text3"), 16), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(lambda _: self._fill())
        sl.addWidget(self.search)
        lv.addWidget(sw)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Run", "Date"])
        self.tree.setRootIsDecorated(True)
        self.tree.setTextElideMode(Qt.ElideMiddle)        # keep the distinctive end of long run names visible
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setStretchLastSection(False)
        self.tree.itemSelectionChanged.connect(self._select)
        self.tree.itemChanged.connect(self._checked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        lv.addWidget(self.tree, 1)
        self.folders_lab = label("", "hint", wrap=True)
        fw = QWidget()
        fl = QVBoxLayout(fw)
        fl.setContentsMargins(12, 4, 12, 4)
        fl.addWidget(self.folders_lab)
        cmp_btn = push("Compare ticked runs", icon_name="compare")
        cmp_btn.clicked.connect(self._show_compare)
        fl.addWidget(cmp_btn)
        lv.addWidget(fw)
        left.setMinimumWidth(360)
        sp.addWidget(left)
        right = QFrame()
        right.setObjectName("pane")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        rl.addWidget(self.stack)
        empty = QWidget()
        el = QVBoxLayout(empty)
        el.addStretch()
        ic = QLabel()
        ic.setPixmap(icons.pixmap("results", T.c("text3"), 56))
        ic.setAlignment(Qt.AlignCenter)
        el.addWidget(ic)
        t = label("Select a run on the left", "h3")
        t.setAlignment(Qt.AlignCenter)
        el.addWidget(t)
        self.empty_title = t
        t2 = label("Runs started from the Studio and runs made with the PASCHEN-1D notebooks are listed here.",
                   "muted")
        t2.setAlignment(Qt.AlignCenter)
        el.addWidget(t2)
        self.empty_sub = t2
        el.addStretch()
        self.stack.addWidget(empty)
        self.run_view = RunView(self)
        self.run_view.loadModel.connect(self.loadModel.emit)
        self.run_view.deleted.connect(self.refresh)
        self.stack.addWidget(self.run_view)
        self.compare_view = CompareView(self)
        self.stack.addWidget(self.compare_view)
        self.sweep_view = SweepView(self)
        self.stack.addWidget(self.sweep_view)
        sp.addWidget(right)
        sp.setSizes([430, 1000])
        sp.setStretchFactor(1, 1)
        self._checked_paths: set[str] = set()

    def refresh(self, select: str | None = None):
        folders = self.folders_fn()
        self.infos = discover(folders)
        self.folders_lab.setText("Scanning: " + " · ".join(str(f) for f in folders))
        self._fill(select)
        none = not self.infos                 # say what to do next instead of "select a run" with no runs
        self.empty_title.setText("No results yet" if none else "Select a run on the left")
        self.empty_sub.setText("Run a model on the Simulate page – finished runs appear here automatically, together "
                               "with runs made with the PASCHEN-1D notebooks." if none else
                               "Runs started from the Studio and runs made with the PASCHEN-1D notebooks are listed "
                               "here. Tick several to compare them.")

    def _fill(self, select: str | None = None):
        q = self.search.text().strip().lower()
        self.tree.blockSignals(True)
        self.tree.clear()
        sweeps = {}
        singles = []
        for info in self.infos:
            if q and q not in f"{info.name} {info.title} {info.case}".lower():
                continue
            sw = (info.studio or {}).get("sweep") or None
            if sw and sw.get("id"):
                sweeps.setdefault(sw["id"], []).append(info)
            else:
                singles.append(info)
        sel_item = None
        for sid, runs in sweeps.items():
            sw = runs[0].studio.get("sweep", {})
            it = QTreeWidgetItem([f"Sweep · {sw.get('label') or sw.get('parameter')}", f"{len(runs)} runs"])
            it.setIcon(0, icons.icon("sweep", T.c("accent"), 16))
            it.setData(0, Qt.UserRole, ("sweep", sid))
            f = it.font(0)
            f.setBold(True)
            it.setFont(0, f)
            self.tree.addTopLevelItem(it)
            for info in sorted(runs, key=lambda r: r.studio.get("sweep", {}).get("index", 0)):
                c = self._run_item(info)
                it.addChild(c)
                if select and str(info.path) == select:
                    sel_item = c
        for info in singles:
            c = self._run_item(info)
            self.tree.addTopLevelItem(c)
            if select and str(info.path) == select:
                sel_item = c
        self.tree.blockSignals(False)
        if sel_item is not None:
            self.tree.setCurrentItem(sel_item)

    def _run_item(self, info):
        import datetime as dt
        # status is shown by the coloured dot (and in the tooltip) so the run name gets the width
        c = QTreeWidgetItem([info.name, dt.datetime.fromtimestamp(info.mtime).strftime("%m-%d %H:%M")])
        c.setData(0, Qt.UserRole, ("run", str(info.path)))
        c.setFlags(c.flags() | Qt.ItemIsUserCheckable)
        c.setCheckState(0, Qt.Checked if str(info.path) in self._checked_paths else Qt.Unchecked)
        col = {"finished": T.c("success"), "stopped": T.c("warning"), "failed": T.c("danger"),
               "aborted": T.c("danger"), "running": T.c("accent"), "paused": T.c("warning")}.get(info.status,
                                                                                               T.c("text3"))
        c.setIcon(0, icons.icon("dot", col, 12))
        tip = (f"{info.title}\nStatus: {info.status}\n{info.path}\n"
               f"{'Studio run' if info.source == 'studio' else 'notebook/script run'}")
        c.setToolTip(0, tip)
        c.setToolTip(1, tip)
        return c

    def _checked(self, item, col):
        d = item.data(0, Qt.UserRole)
        if d and d[0] == "run":
            if item.checkState(0) == Qt.Checked:
                self._checked_paths.add(d[1])
            else:
                self._checked_paths.discard(d[1])
            if self.stack.currentWidget() is self.compare_view:
                self.compare_view.render()

    def checked_runs(self):
        return [i for i in self.infos if str(i.path) in self._checked_paths]

    def _select(self):
        it = self.tree.currentItem()
        if it is None:
            return
        kind, key = it.data(0, Qt.UserRole)
        if kind == "run":
            info = next((i for i in self.infos if str(i.path) == key), None)
            if info is not None:
                self.stack.setCurrentWidget(self.run_view)
                self.run_view.set_run(info)
        elif kind == "sweep":
            runs = [i for i in self.infos if ((i.studio or {}).get("sweep") or {}).get("id") == key]
            self.stack.setCurrentWidget(self.sweep_view)
            self.sweep_view.set_sweep(key, runs)

    def _show_compare(self):
        self.stack.setCurrentWidget(self.compare_view)
        self.compare_view.render()

    def open_run(self, path: str):
        self.refresh(select=str(Path(path)))
        if self.tree.currentItem() is None:
            for info in self.infos:
                if info.path.resolve() == Path(path).resolve():
                    self.stack.setCurrentWidget(self.run_view)
                    self.run_view.set_run(info)
                    break

    def _add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Folder that contains run folders")
        if not d:
            return
        extra = list(self.settings.value("result_folders", []) or [])
        if d not in extra:
            extra.append(d)
            self.settings.setValue("result_folders", extra)
        self.refresh()

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        if it is None:
            return
        kind, key = it.data(0, Qt.UserRole)
        if kind != "run":
            return
        m = QMenu(self)
        m.addAction("Show folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(key)))
        m.addAction("Copy path", lambda: QGuiApplication.clipboard().setText(key))
        if (Path(key) / "studio_model.p1d.json").exists():
            m.addAction("Open model in builder", lambda: self.loadModel.emit(str(Path(key) / "studio_model.p1d.json")))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def restyle(self):
        self.run_view.restyle()
        self._fill()
