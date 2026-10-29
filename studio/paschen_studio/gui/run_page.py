"""Simulation page: run queue, progress, live monitor and solver log."""
from __future__ import annotations

import time

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QProgressBar, QSizePolicy, QSplitter, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..runs import RunData, health, health_message
from ..units import format_quantity, human_duration
from . import icons
from . import theme as T
from .builder import pane
from .plotting import PlotCanvas
from .runplots import history_spec, profiles_spec
from .widgets import ElidedLabel, RunButton, StatTile, badge, icon_button, label, push

LIVE_PROFILE_CHOICES = [("Densities nₑ, nᵢ", ["ne", "ni"]), ("Potential φ", ["phi"]), ("Electric field E", ["E"]),
                        ("Fluxes Γₑ, Γᵢ", ["Gamma_e", "Gamma_i"]), ("Net source S", ["S"]),
                        ("Ionization frequency νᵢ", ["nu_i"])]
LIVE_HISTORY_CHOICES = [("Voltages", ["V_app", "V_node", "V_gap"]), ("Discharge current", ["I_discharge"]),
                        ("Current components", ["I_discharge", "I_transport_plasma", "I_displacement_gap"]),
                        ("Drift CFL", ["cfl"]), ("Diffusion number", ["diffusion_cfl"]),
                        ("Adaptive sub-steps", ["adaptive_substeps"])]


class JobItem(QWidget):
    def __init__(self, job, parent=None):
        super().__init__(parent)
        self.job = job
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 7, 8, 7)
        v.setSpacing(4)
        top = QHBoxLayout()
        self.title = ElidedLabel(job.label)
        f = self.title.font()
        f.setBold(True)
        self.title.setFont(f)
        top.addWidget(self.title, 1)
        self.badge = badge(job.status)
        top.addWidget(self.badge)
        v.addLayout(top)
        self.sub = ElidedLabel("")
        self.sub.setObjectName("hint")
        v.addWidget(self.sub)
        self.bar = QProgressBar()
        self.bar.setObjectName("thin")
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        v.addWidget(self.bar)
        self.update_view()

    def update_view(self):
        j = self.job
        self.badge.setText(j.status.capitalize())
        self.badge.setObjectName(f"badge_{j.status}")
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        self.bar.setValue(int(1000 * j.fraction))
        if j.status == "queued":
            txt = f"{j.run_name} · waiting"
        elif j.active:
            txt = f"{j.run_name} · {100 * j.fraction:.1f} %" + (f" · ETA {human_duration(j.eta)}" if j.eta else
                                                                f" · {j.phase}")
        else:
            txt = f"{j.run_name} · {human_duration(j.elapsed)}" + (f" · {j.error[:60]}" if j.error else "")
        self.sub.setText(txt)


class RunPage(QWidget):
    openResults = Signal(str)          # run dir
    requestRun = Signal()
    requestTest = Signal()
    requestSweep = Signal()
    requestModel = Signal()            # "go to the Model page" (to fix errors)

    def __init__(self, manager, settings, parent=None):
        super().__init__(parent)
        self.m = manager
        self.settings = settings
        self.current = None
        self._items = {}
        self._rd = None
        self._rd_job = None
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        sp = QSplitter(Qt.Horizontal)
        sp.setChildrenCollapsible(False)
        root.addWidget(sp)

        # ---- queue ----
        left, lv, lh, _ = pane("Run queue")
        bw = QWidget()
        bl = QVBoxLayout(bw)
        bl.setContentsMargins(10, 10, 10, 6)
        bl.setSpacing(6)
        # one start button; test run and sweep are in its menu
        self.b_run = RunButton("Run current model", tip="Run the model that is open on the Model page (F5)")
        self.b_run.main.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.b_run.clicked.connect(self.requestRun.emit)
        self.b_run.add_action("Test run – 2 % of the time steps", self.requestTest.emit, "flask", "Shift+F5")
        self.b_run.add_action("Parameter sweep…", self.requestSweep.emit, "sweep", "Ctrl+Shift+R")
        bl.addWidget(self.b_run)
        lv.addWidget(bw)
        self.list = QListWidget()
        self.list.setSpacing(2)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.currentRowChanged.connect(self._select_row)
        lv.addWidget(self.list, 1)
        self.empty_q = label("Runs you start appear here, newest first. Several can run at the same time "
                             "(Preferences → Simultaneous runs).", "hint", wrap=True)
        ew = QWidget()
        el = QVBoxLayout(ew)
        el.setContentsMargins(14, 0, 14, 10)
        el.addWidget(self.empty_q)
        lv.addWidget(ew)
        cb = push("Clear finished", "ghost", icon_name="trash")
        cb.clicked.connect(self._clear)
        self.b_clear = cb
        cw = QWidget()
        cl = QHBoxLayout(cw)
        cl.setContentsMargins(10, 0, 10, 10)
        cl.addWidget(cb)
        cl.addStretch()
        lv.addWidget(cw)
        left.setMinimumWidth(300)
        sp.addWidget(left)

        # ---- empty state: what happens here and the one next step ----
        self.detail = QStackedWidget()
        self.detail.addWidget(self._build_empty())
        # ---- detail ----
        right = QFrame()
        right.setObjectName("pane")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(16, 12, 16, 12)
        rv.setSpacing(10)
        hdr = QHBoxLayout()
        self.d_title = label("No run selected", "h3")
        hdr.addWidget(self.d_title)
        self.d_badge = badge("info", "–")
        hdr.addWidget(self.d_badge)
        hdr.addStretch()
        self.b_pause = push("Pause", icon_name="pause")
        self.b_pause.clicked.connect(self._pause)
        self.b_stop = push("Stop && keep results", icon_name="stop")
        self.b_stop.setToolTip("End the time loop now. The solver still writes run_metadata.json, so the partial "
                               "run can be analysed like any other.")
        self.b_stop.clicked.connect(lambda: self.current and self.m.stop(self.current))
        self.b_abort = push("Abort", "danger", icon_name="close", icon_color=T.c("danger"))
        self.b_abort.clicked.connect(lambda: self.current and self.m.abort(self.current))
        self.b_results = push("Open in Results", "primary", icon_name="results")
        self.b_results.clicked.connect(lambda: self.current and self.openResults.emit(str(self.current.run_dir)))
        self.b_folder = icon_button("folder", "Show the run folder", size=18)
        self.b_folder.clicked.connect(lambda: self.current and QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.current.run_dir if self.current.run_dir.exists() else self.current.workspace))))
        for b in (self.b_pause, self.b_stop, self.b_abort, self.b_results, self.b_folder):
            hdr.addWidget(b)
        rv.addLayout(hdr)
        self.d_path = label("", "hint", selectable=True)
        rv.addWidget(self.d_path)
        # progress card
        pc = QFrame()
        pc.setObjectName("cardFlat")
        pl = QVBoxLayout(pc)
        pl.setContentsMargins(14, 10, 14, 10)
        top = QHBoxLayout()
        self.pct = label("0 %", "h1")
        top.addWidget(self.pct)
        pv = QVBoxLayout()
        self.phase = label("", "muted")
        pv.addWidget(self.phase)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        pv.addWidget(self.bar)
        top.addLayout(pv, 1)
        pl.addLayout(top)
        g = QHBoxLayout()
        self.t_elapsed = StatTile("Elapsed", "–", "", "clock")
        self.t_eta = StatTile("Remaining", "–", "", "clock")
        self.t_rate = StatTile("Speed", "–", "", "cpu")
        self.t_sim = StatTile("Simulated time", "–", "", "wave")
        for t in (self.t_elapsed, self.t_eta, self.t_rate, self.t_sim):
            g.addWidget(t)
        pl.addLayout(g)
        rv.addWidget(pc)
        self.health_banner = label("", wrap=True)
        self.health_banner.setStyleSheet(f"background: {T.c('danger_soft')}; color: {T.c('danger')}; "
                                         "border-radius: 8px; padding: 8px 12px; font-weight: 600;")
        self.health_banner.hide()
        rv.addWidget(self.health_banner)
        # live plots / log
        self.stack = QStackedWidget()
        live = QWidget()
        lg = QGridLayout(live)
        lg.setContentsMargins(0, 0, 0, 0)
        lg.setSpacing(10)
        self.p_prof1 = self._live_plot("profile", 0)
        self.p_prof2 = self._live_plot("profile", 2)
        self.p_hist1 = self._live_plot("history", 0)
        self.p_hist2 = self._live_plot("history", 1)
        lg.addWidget(self.p_prof1[0], 0, 0)
        lg.addWidget(self.p_prof2[0], 0, 1)
        lg.addWidget(self.p_hist1[0], 1, 0)
        lg.addWidget(self.p_hist2[0], 1, 1)
        self.stack.addWidget(live)
        self.console = QPlainTextEdit()
        self.console.setObjectName("console")
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(5000)
        tabs = QHBoxLayout()
        self.tab_live = push("Live monitor", "ghost", icon_name="results")
        self.tab_log = push("Solver log", "ghost", icon_name="terminal")
        self.tab_live.clicked.connect(lambda: self._tab(0))
        self.tab_log.clicked.connect(lambda: self._tab(1))
        tabs.addWidget(self.tab_live)
        tabs.addWidget(self.tab_log)
        tabs.addStretch()
        self.live_note = label("", "hint")
        tabs.addWidget(self.live_note)
        rv.addLayout(tabs)
        self.stack.addWidget(self.console)
        rv.addWidget(self.stack, 1)
        self.detail.addWidget(right)
        sp.addWidget(self.detail)
        sp.setSizes([300, 1100])
        sp.setStretchFactor(1, 1)
        self._tab(0)
        self._update_clear()

        manager.added.connect(self._added)
        manager.changed.connect(self._changed)
        manager.logged.connect(self._logged)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._live)
        self.timer.start(int(settings.value("live_interval_ms", 1000)))
        self._show_job(None)

    # -- widgets --------------------------------------------------------------
    def _build_empty(self):
        w = QFrame()
        w.setObjectName("pane")
        outer = QVBoxLayout(w)
        outer.addStretch(2)
        box = QWidget()
        box.setMaximumWidth(560)
        v = QVBoxLayout(box)
        v.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("play", T.c("success"), 40))
        ic.setAlignment(Qt.AlignCenter)
        v.addWidget(ic)
        self.e_title = label("Ready to run", "h2")
        self.e_title.setAlignment(Qt.AlignCenter)
        self.e_title.setWordWrap(True)
        v.addWidget(self.e_title)
        self.e_sub = label("", "muted", wrap=True)
        self.e_sub.setAlignment(Qt.AlignCenter)
        v.addWidget(self.e_sub)
        row = QHBoxLayout()
        row.addStretch()
        self.e_run = push("Run", "run", icon_name="play", tip="Run the model (F5)")
        self.e_run.clicked.connect(self.requestRun.emit)
        row.addWidget(self.e_run)
        self.e_test = push("Test run first", icon_name="flask",
                           tip="Run 2 % of the time steps with the same dt – checks the setup in seconds (Shift+F5)")
        self.e_test.clicked.connect(self.requestTest.emit)
        row.addWidget(self.e_test)
        self.e_model = push("Go to the Model page", "primary", icon_name="model")
        self.e_model.clicked.connect(self.requestModel.emit)
        row.addWidget(self.e_model)
        row.addStretch()
        v.addLayout(row)
        how = label("While a run is going you will see its progress, live profiles (densities, fields) and "
                    "time traces (voltages, currents) here, plus the solver log. Pause, stop early with results "
                    "kept, or abort at any time.", "hint", wrap=True)
        how.setAlignment(Qt.AlignCenter)
        v.addSpacing(6)
        v.addWidget(how)
        h = QHBoxLayout()
        h.addStretch()
        h.addWidget(box, 10)
        h.addStretch()
        outer.addLayout(h)
        outer.addStretch(3)
        self.set_model_info("the current model", "", 0)
        return w

    def set_model_info(self, title: str, summary: str, n_errors: int):
        """What the empty state offers: run the open model, or go fix it first."""
        if n_errors:
            self.e_title.setText(f"{title} is not ready to run")
            self.e_sub.setText(f"The model check found {n_errors} error{'s' * (n_errors != 1)}. Fix "
                               f"{'them' if n_errors != 1 else 'it'} on the Model page – most have a one-click fix.")
        else:
            self.e_title.setText(f"Ready to run: {title}")
            self.e_sub.setText(summary)
        self.e_run.setVisible(not n_errors)
        self.e_test.setVisible(not n_errors)
        self.e_model.setVisible(bool(n_errors))

    def _live_plot(self, kind, default_idx):
        w = QFrame()
        w.setObjectName("cardFlat")
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 6, 8, 4)
        v.setSpacing(2)
        combo = QComboBox()
        for name, qs in (LIVE_PROFILE_CHOICES if kind == "profile" else LIVE_HISTORY_CHOICES):
            combo.addItem(name, qs)
        combo.setCurrentIndex(default_idx)
        combo.setMinimumContentsLength(12)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        canvas = PlotCanvas("", height=170, export_name="live")
        canvas.bar.layout().insertWidget(0, combo)
        combo.currentIndexChanged.connect(lambda _=None: (canvas.reset_view(), self._live(force=True)))
        v.addWidget(canvas)
        return w, combo, canvas

    def _tab(self, i):
        self.stack.setCurrentIndex(i)
        self.tab_live.setObjectName("primary" if i == 0 else "ghost")
        self.tab_log.setObjectName("primary" if i == 1 else "ghost")
        for b in (self.tab_live, self.tab_log):
            b.style().unpolish(b)
            b.style().polish(b)
        self.tab_live.setIcon(icons.icon("results", "#ffffff" if i == 0 else T.c("text2"), 16))
        self.tab_log.setIcon(icons.icon("terminal", "#ffffff" if i == 1 else T.c("text2"), 16))

    # -- queue ------------------------------------------------------------------
    def _added(self, job):
        it = QListWidgetItem()
        w = JobItem(job)
        it.setSizeHint(w.sizeHint() + QSize(0, 6))
        self.list.insertItem(0, it)
        self.list.setItemWidget(it, w)
        self._items[job.id] = (it, w)
        self.list.setCurrentRow(0)
        self.empty_q.setVisible(False)
        self._update_clear()

    def _update_clear(self):
        self.b_clear.setVisible(any(j.done for j in self.m.jobs))
        # with no runs yet the empty state on the right offers Run; avoid a second identical button
        self.b_run.setVisible(bool(self.m.jobs))

    def _changed(self, job):
        self._update_clear()
        if job.id in self._items:
            self._items[job.id][1].update_view()
        if job is self.current:
            self._show_job(job, partial=True)

    def _logged(self, job, line):
        if job is self.current:
            self.console.appendPlainText(line)

    def _select_row(self, row):
        it = self.list.item(row)
        if it is None:
            return
        w = self.list.itemWidget(it)
        if w is not None:
            self._show_job(w.job)

    def select_job(self, job):
        if job.id in self._items:
            self.list.setCurrentItem(self._items[job.id][0])

    def _clear(self):
        for j in list(self.m.jobs):
            if j.done:
                it, w = self._items.pop(j.id, (None, None))
                if it is not None:
                    self.list.takeItem(self.list.row(it))
        self.m.clear_done()
        if self.current is not None and self.current.done:
            self._show_job(None)
        self.empty_q.setVisible(self.list.count() == 0)
        self._update_clear()

    # -- detail -----------------------------------------------------------------
    def _show_job(self, job, partial=False):
        if not partial:
            self.current = job
            self.console.clear()
            if job is not None:
                self.console.setPlainText("\n".join(job.log))
                self.console.moveCursor(QTextCursor.End)
            self._rd = None
            self._health_t = 0.0
            self.health_banner.hide()
            for _, combo, canvas in (self.p_prof1, self.p_prof2, self.p_hist1, self.p_hist2):
                canvas.clear("Waiting for data…" if job else "")
        has = job is not None
        self.detail.setCurrentIndex(1 if has else 0)
        for b in (self.b_pause, self.b_stop, self.b_abort, self.b_results, self.b_folder):
            b.setEnabled(has)
        if not has:
            self.d_title.setText("No run selected")
            self.d_badge.setVisible(False)
            self.d_path.setText("")
            self.pct.setText("–")
            self.phase.setText("Start a run from the Model page (F5) or with the buttons on the left.")
            self.bar.setValue(0)
            return
        self.d_title.setText(job.label)
        self.d_badge.setVisible(True)
        self.d_badge.setText(job.status.capitalize())
        self.d_badge.setObjectName(f"badge_{job.status}")
        self.d_badge.style().unpolish(self.d_badge)
        self.d_badge.style().polish(self.d_badge)
        self.d_path.setText(str(job.run_dir))
        self.b_pause.setText("Resume" if job.status == "paused" else "Pause")
        self.b_pause.setIcon(icons.icon("play" if job.status == "paused" else "pause", T.c("text2"), 16))
        # show only the controls that can act on this run (no rows of greyed-out buttons)
        live = job.active or job.status == "queued"
        self.b_pause.setVisible(job.status in ("running", "paused"))
        self.b_stop.setVisible(live)
        self.b_abort.setVisible(live)
        self.b_results.setVisible(job.done and job.status in ("finished", "stopped"))
        self.pct.setText(f"{100 * job.fraction:.1f} %")
        self.bar.setValue(int(1000 * job.fraction))
        ph = {"queued": "Waiting in the queue", "starting": "Starting…", "finished": "Finished",
              "stopped": "Stopped early – results kept", "failed": "Failed", "aborted": "Aborted"}.get(job.status)
        self.phase.setText(ph or (job.phase + (f" · {job.sub}" if job.sub else "") +
                                  ("  (first run compiles Numba kernels)" if job.n == 0 and "setup" in job.phase
                                   else "")))
        if job.status == "failed" and job.error:
            self.phase.setText(f"Failed: {job.error}")
        el = job.elapsed if job.done else ((time.time() - job.started) if job.started else 0)
        self.t_elapsed.set(human_duration(el))
        self.t_eta.set(human_duration(job.eta) if (job.eta is not None and job.active) else "–")
        self.t_rate.set(f"{job.rate:,.0f}" if job.rate else "–", "steps / s")
        g = job.grid
        if g:
            self.t_sim.set(format_quantity(job.t_sim(), "s"), f"of {format_quantity(float(g['T_total']), 's')}")

    def _pause(self):
        j = self.current
        if j is None:
            return
        if j.status == "paused":
            self.m.resume(j)
        else:
            self.m.pause(j)

    # -- live --------------------------------------------------------------------
    def _live(self, force=False):
        j = self.current
        if j is None or not self.isVisible():
            return
        if j.active and j.started:
            self.t_elapsed.set(human_duration(time.time() - j.started))
        if not (j.active or force or (j.done and self._rd_job != (j.id, j.status))):
            return
        if not j.run_dir.exists() or not (j.run_dir / "studio_run.json").exists():
            return
        if j.n <= 0 and not j.done:
            return
        try:
            if self._rd is None or self._rd_job is None or self._rd_job[0] != j.id:
                self._rd = RunData.open(j.run_dir, steps_done=max(j.n, 0))
            self._rd.steps_done = max(0, min(j.n, self._rd.Nt - 1))
            self._rd_job = (j.id, j.status)
            rd = self._rd
            k = rd.nsave_valid - 1
            self.live_note.setText(f"snapshot {k + 1:,} / {rd.nsave_total:,}  ·  t = "
                                   f"{format_quantity(rd.snapshot_times()[-1] if k >= 0 else 0, 's')}")
            for _, combo, canvas in (self.p_prof1, self.p_prof2):
                qs = combo.currentData()
                spec = profiles_spec(rd, k, qs)
                for a in spec.axes:
                    a.title = ""
                canvas.set_spec(spec)
            for _, combo, canvas in (self.p_hist1, self.p_hist2):
                qs = [q for q in combo.currentData() if q in rd.available_temporal()]
                spec = history_spec(rd, qs, max_points=3000)
                for a in spec.axes:
                    a.title = ""
                canvas.set_spec(spec)
            if time.time() - getattr(self, "_health_t", 0.0) > 4.0 or j.done:
                self._health_t = time.time()
                msg = health_message(health(rd))
                self.health_banner.setText("⚠ " + msg if msg else "")
                self.health_banner.setVisible(bool(msg))
        except Exception as exc:  # pragma: no cover - live view must never crash the app
            self.live_note.setText(f"live view: {exc}")

    def restyle(self):
        for _, _, c in (self.p_prof1, self.p_prof2, self.p_hist1, self.p_hist2):
            c.restyle()
        self._tab(self.stack.currentIndex())
