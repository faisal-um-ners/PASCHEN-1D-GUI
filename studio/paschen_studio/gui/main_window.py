"""Main window: navigation rail, header actions, pages, menus and the run queue."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QFileDialog, QFrame, QHBoxLayout,
                               QInputDialog, QLabel, QMainWindow, QMessageBox, QProgressBar, QStackedWidget,
                               QToolButton, QVBoxLayout, QWidget)

from .. import (APP_NAME, ARXIV_URL, MODEL_SUFFIX, PAPER_URL, REPO_URL, __version__)
from .. import advisor as A
from .. import solver as S
from ..model import StudioModel, new_model_from_case, unique_run_name
from ..sweep import sweep_jobs
from ..units import human_bytes, human_duration
from . import icons
from . import theme as T
from .builder import ModelPage
from .dialogs import AboutDialog, FindSettingDialog, IonBrowserDialog, PreferencesDialog
from .help_page import HelpPage
from .home_page import HomePage
from .jobs import JobManager
from .results_page import ResultsPage
from .run_page import RunPage
from .widgets import RunButton, label, push

PAGES = [("home", "Home", "home"), ("model", "Model", "model"), ("run", "Simulate", "play"),
         ("results", "Results", "results"), ("help", "Help", "help")]

STEP_TIPS = {"home": "Home – choose a starting point", "model": "Step 1 of 3 – build and check the model",
             "run": "Step 2 of 3 – run the simulation", "results": "Step 3 of 3 – explore the results",
             "help": "Help and documentation"}
CRUMBS = {"home": "WELCOME", "model": "STEP 1 OF 3 · BUILD THE MODEL", "run": "STEP 2 OF 3 · RUN",
          "results": "STEP 3 OF 3 · EXPLORE RESULTS", "help": "HELP"}

DEMO_OVERRIDES = {
    # coarse but complete version of the paper's nitrogen DBD benchmark (~1 minute on a laptop core)
    "config_case_nitrogen_pulsed_discharge": {"numerics.Nx": 400, "numerics.Nt": 60_000,
                                              "numerics.use_adaptive_substepping": True,
                                              "output.save_every": 150},
}


def default_workspace() -> Path:
    d = S.studio_dir() / "runs"
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write_test"
        probe.write_text("ok")
        probe.unlink()
        return d
    except OSError:
        d = Path.home() / "PASCHEN-1D-Studio" / "runs"
        d.mkdir(parents=True, exist_ok=True)
        return d


class MainWindow(QMainWindow):
    def __init__(self, path: str | None = None):
        super().__init__()
        self.settings = QSettings()
        ws = self.settings.value("workspace", "")
        self.workspace = Path(ws) if ws else default_workspace()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.model = new_model_from_case("config_case_argon_dc_discharge")
        self.dirty = False
        self.jobs = JobManager(self.settings, self)
        self.jobs.finished.connect(self._job_finished)
        self.jobs.changed.connect(lambda _: self._update_status())
        self.resize(1560, 960)
        self.setMinimumSize(1100, 700)
        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        self._build_ui()
        self._build_menus()
        self.set_model(self.model, dirty=False)
        if path:
            QTimer.singleShot(0, lambda: self.open_model(path))
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(1000)

    # ======================================================================
    # UI
    # ======================================================================
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("pageRoot")
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        rail = QFrame()
        rail.setObjectName("navRail")
        rail.setFixedWidth(84)
        rv = QVBoxLayout(rail)
        rv.setContentsMargins(8, 14, 8, 12)
        rv.setSpacing(6)
        logo = QLabel()
        logo.setPixmap(icons.logo_pixmap(40))
        logo.setAlignment(Qt.AlignCenter)
        logo.setObjectName("navBrand")
        logo.setToolTip(f"{APP_NAME} {__version__}")
        rv.addWidget(logo)
        rv.addSpacing(14)
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        self.nav_btns = {}
        for i, (key, text, ic) in enumerate(PAGES):
            b = QToolButton()
            b.setText(text)
            b.setIcon(icons.icon(ic, T.c("rail_text"), 22, active_color="#ffffff"))
            b.setIconSize(QSize(22, 22))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setCheckable(True)
            b.setFixedSize(68, 60)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f"{STEP_TIPS.get(key, text)}  (Ctrl+{i + 1})")
            self.nav.addButton(b, i)
            self.nav_btns[key] = b
            rv.addWidget(b, 0, Qt.AlignHCenter)
        self.run_dot = QLabel(self.nav_btns["run"])
        self.run_dot.setFixedSize(18, 18)
        self.run_dot.setAlignment(Qt.AlignCenter)
        self.run_dot.setStyleSheet(f"background: {T.c('success')}; color: white; border-radius: 9px; "
                                   "font-size: 8pt; font-weight: 700;")
        self.run_dot.move(44, 4)
        self.run_dot.hide()
        rv.addStretch()
        self.b_theme = QToolButton()
        self.b_theme.setIcon(icons.icon("moon" if T.current()["name"] == "light" else "sun", T.c("rail_text"), 20))
        self.b_theme.setToolTip("Toggle light / dark theme (Ctrl+Shift+D)")
        self.b_theme.setFixedSize(68, 40)
        self.b_theme.clicked.connect(self.toggle_theme)
        rv.addWidget(self.b_theme, 0, Qt.AlignHCenter)
        b_pref = QToolButton()
        b_pref.setIcon(icons.icon("settings", T.c("rail_text"), 20))
        b_pref.setToolTip("Preferences")
        b_pref.setFixedSize(68, 40)
        b_pref.clicked.connect(self.preferences)
        rv.addWidget(b_pref, 0, Qt.AlignHCenter)
        h.addWidget(rail)

        main = QWidget()
        mv = QVBoxLayout(main)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(0)
        header = QFrame()
        header.setObjectName("headerBar")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 10, 16, 10)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        self.crumb = label("", "crumb")
        tv.addWidget(self.crumb)
        self.h_title = label("", "headerTitle")
        tv.addWidget(self.h_title)
        hl.addLayout(tv, 1)
        self.b_undo = push("", "ghost", icon_name="undo", tip="Undo (Ctrl+Z)")
        self.b_redo = push("", "ghost", icon_name="redo", tip="Redo (Ctrl+Shift+Z)")
        self.b_undo.clicked.connect(self.undo)
        self.b_redo.clicked.connect(self.redo)
        self.b_save = push("Save", icon_name="save", tip="Save the model (Ctrl+S)")
        self.b_save.clicked.connect(self.save)
        # one primary action; the variants live in its small menu (progressive disclosure)
        self.b_runh = RunButton("Run", tip="Run the model (F5)")
        self.b_runh.clicked.connect(lambda: self.run_current())
        self.b_runh.add_action("Test run – 2 % of the time steps", lambda: self.run_current(test=True), "flask",
                               "Shift+F5")
        self.b_runh.add_action("Parameter sweep…", self.sweep, "sweep", "Ctrl+Shift+R")
        self.b_runh.menu.addSeparator()
        self.b_runh.add_action("Check the model now", self.check, "check", "Ctrl+Shift+K")
        for b in (self.b_undo, self.b_redo, self.b_save, self.b_runh):
            hl.addWidget(b)
        mv.addWidget(header)

        self.stack = QStackedWidget()
        self.home = HomePage(self.settings)
        self.home.newWizard.connect(self.new_wizard)
        self.home.openModel.connect(lambda: self.open_model())
        self.home.openCase.connect(self.new_from_case)
        self.home.demoCase.connect(self.demo_case)
        self.home.openRecent.connect(self.open_model)
        self.home.showHelp.connect(self.show_help)
        self.model_page = ModelPage(self.settings)
        self.model_page.modelEdited.connect(self._edited)
        self.model_page.requestChangeCase.connect(self.change_case)
        self.model_page.requestIonBrowser.connect(self.ion_browser)
        self.model_page.requestFix.connect(self.apply_fix)
        self.model_page.find_btn.clicked.connect(self.find_setting)
        self.run_page = RunPage(self.jobs, self.settings)
        self.run_page.openResults.connect(self.open_results)
        self.run_page.requestRun.connect(lambda: self.run_current())
        self.run_page.requestTest.connect(lambda: self.run_current(test=True))
        self.run_page.requestSweep.connect(self.sweep)
        self.run_page.requestModel.connect(lambda: self.go(1))
        self.results = ResultsPage(self.settings, self.result_folders)
        self.results.loadModel.connect(self.open_model)
        self.help = HelpPage()
        for w in (self.home, self.model_page, self.run_page, self.results, self.help):
            self.stack.addWidget(w)
        mv.addWidget(self.stack, 1)
        h.addWidget(main, 1)
        self.setCentralWidget(central)
        self.nav.idClicked.connect(self.go)
        sb = self.statusBar()
        self.s_solver = label("")
        self.s_ws = label("")
        self.s_jobs = label("")
        self.s_prog = QProgressBar()
        self.s_prog.setObjectName("thin")
        self.s_prog.setFixedWidth(160)
        self.s_prog.setRange(0, 1000)
        self.s_prog.hide()
        sb.addWidget(self.s_solver)
        sb.addWidget(self.s_ws, 1)
        sb.addPermanentWidget(self.s_jobs)
        sb.addPermanentWidget(self.s_prog)
        sv, _ = S.solver_version()
        self.s_solver.setText(f"PASCHEN-1D {sv}")
        self.s_ws.setText(f"Workspace: {self.workspace}")
        self.go(0)

    def _build_menus(self):
        mb = self.menuBar()
        mb.clear()

        def act(menu, text, slot, shortcut=None, icon=None):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if icon:
                a.setIcon(icons.icon(icon, T.c("text2"), 16))
            a.triggered.connect(slot)
            menu.addAction(a)
            return a

        f = mb.addMenu("&File")
        act(f, "New simulation (guided)…", self.new_wizard, "Ctrl+N", "wizard")
        nm = f.addMenu("New from case")
        for c in S.list_cases():
            act(nm, c.title, lambda _=None, m=c.module: self.new_from_case(m))
        act(f, "Open model…", lambda: self.open_model(), "Ctrl+O", "open")
        self.recent_menu = f.addMenu("Open recent")
        self._fill_recent()
        f.addSeparator()
        act(f, "Save", self.save, "Ctrl+S", "save")
        act(f, "Save as…", self.save_as, "Ctrl+Shift+S")
        f.addSeparator()
        act(f, "Export Python run script…", self.export_script, None, "export")
        act(f, "Import a case module (.py)…", self.import_case, None, "layers")
        f.addSeparator()
        act(f, "Run workspace folder…", self.choose_workspace, None, "folder")
        act(f, "Preferences…", self.preferences, "Ctrl+,", "settings")
        f.addSeparator()
        act(f, "Quit", self.close, "Ctrl+Q")
        e = mb.addMenu("&Edit")
        act(e, "Undo", self.undo, "Ctrl+Z", "undo")
        act(e, "Redo", self.redo, "Ctrl+Shift+Z", "redo")
        e.addSeparator()
        act(e, "Find a setting…", self.find_setting, "Ctrl+K", "search")
        m = mb.addMenu("&Model")
        act(m, "Check model", self.check, "Ctrl+Shift+K", "check")
        act(m, "Change base case…", self.change_case, None, "layers")
        act(m, "Ion transport library…", self.ion_browser, None, "ion")
        act(m, "Configure transport for the current gas", lambda: self.apply_fix("auto_gas"), None, "gas")
        act(m, "Reset all settings to the case defaults", self.reset_all, None, "reset")
        r = mb.addMenu("&Run")
        act(r, "Run", lambda: self.run_current(), "F5", "play")
        act(r, "Test run", lambda: self.run_current(test=True), "Shift+F5", "flask")
        act(r, "Parameter sweep…", self.sweep, "Ctrl+Shift+R", "sweep")
        r.addSeparator()
        act(r, "Show simulation queue", lambda: self.go(2), None, "queue")
        res = mb.addMenu("Re&sults")
        act(res, "Open results browser", lambda: self.go(3), None, "results")
        act(res, "Open workspace folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.workspace))),
            None, "folder")
        v = mb.addMenu("&View")
        for i, (key, text, ic) in enumerate(PAGES):
            act(v, text, lambda _=None, k=i: self.go(k), f"Ctrl+{i + 1}", ic)
        v.addSeparator()
        act(v, "Toggle dark theme", self.toggle_theme, "Ctrl+Shift+D", "moon")
        hm = mb.addMenu("&Help")
        act(hm, "Quick start", lambda: self.show_help("quickstart"), "F1", "help")
        act(hm, "Studio user guide", lambda: self.show_help("guide"), None, "book")
        act(hm, "PASCHEN-1D tutorial", lambda: self.show_help("tutorial"), None, "book")
        act(hm, "Keyboard shortcuts", lambda: self.show_help("shortcuts"), None, "settings")
        hm.addSeparator()
        act(hm, "PASCHEN-1D paper", lambda: QDesktopServices.openUrl(QUrl(PAPER_URL)), None, "quote")
        act(hm, "arXiv preprint", lambda: QDesktopServices.openUrl(QUrl(ARXIV_URL)), None, "external")
        act(hm, "GitHub repository", lambda: QDesktopServices.openUrl(QUrl(REPO_URL)), None, "github")
        act(hm, "Cite PASCHEN-1D", lambda: self.show_help("cite"), None, "quote")
        hm.addSeparator()
        act(hm, f"About {APP_NAME}", lambda: AboutDialog(self).exec(), None, "info")

    def _fill_recent(self):
        self.recent_menu.clear()
        items = [p for p in (self.settings.value("recent", []) or []) if p and Path(p).is_file()]
        for p in items[:10]:
            a = self.recent_menu.addAction(Path(p).name)
            a.setToolTip(p)
            a.triggered.connect(lambda _=None, pp=p: self.open_model(pp))
        self.recent_menu.setEnabled(bool(items))

    # ======================================================================
    # navigation
    # ======================================================================
    def go(self, idx: int):
        self.stack.setCurrentIndex(idx)
        btn = self.nav.button(idx)
        if btn:
            btn.setChecked(True)
        key = PAGES[idx][0]
        if key == "results":
            self.results.refresh()
        if key == "home":
            self.home.refresh_recent()
        if key == "run":
            self._refresh_run_page()
        self._update_header()

    def _refresh_run_page(self):
        """Tell the Simulate page's empty state what it would run and whether that can run now."""
        try:
            issues = self.model_page.issues or self.model_page.run_check(deep=False)
            ne = sum(1 for i in issues if i.level == "error")
            e = A.estimate(self.model)
            summary = (f"Estimated run time ≈ {human_duration(e['runtime_s'])} · output ≈ "
                       f"{human_bytes(e['bytes_total'])}. Not sure about the setup? A test run takes seconds.")
        except Exception:
            ne, summary = 0, ""
        self.run_page.set_model_info(self.model.display_title(), summary, ne)

    def _update_header(self):
        idx = self.stack.currentIndex()
        key, text, _ = PAGES[idx]
        title = self.model.display_title() + ("  •" if self.dirty else "")
        self.crumb.setText(CRUMBS[key])
        self.h_title.setText({"home": APP_NAME, "results": "Results browser", "help": "Documentation"}.get(key, title))
        # header actions only where they apply: editing and running belong to the model page
        model_ctx = key == "model"
        for b in (self.b_undo, self.b_redo, self.b_save, self.b_runh):
            b.setVisible(model_ctx)
        self.b_undo.setEnabled(self.model.can_undo())
        self.b_redo.setEnabled(self.model.can_redo())
        self.setWindowTitle(f"{APP_NAME} — {title}")

    def show_help(self, key: str):
        self.go(4)
        self.help.show_page(key)

    # ======================================================================
    # model management
    # ======================================================================
    def set_model(self, model: StudioModel, dirty: bool = False):
        self.model = model
        self.dirty = dirty
        self.model_page.set_model(model, self.workspace)
        self._update_header()

    def _edited(self, paths):
        self.dirty = True
        self._update_header()

    def maybe_save(self) -> bool:
        if not self.dirty or not self.model.overrides and not self.model.path:
            return True
        r = QMessageBox.question(self, "Unsaved changes", f"Save changes to “{self.model.display_title()}”?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if r == QMessageBox.Cancel:
            return False
        if r == QMessageBox.Save:
            return self.save()
        return True

    def new_from_case(self, case: str):
        if not self.maybe_save():
            return
        self.set_model(new_model_from_case(case), dirty=False)
        self.go(1)

    def new_wizard(self, start_case: str | None = None):
        from .wizard import NewSimulationWizard
        if not self.maybe_save():
            return
        dlg = NewSimulationWizard(self, workspace=self.workspace, start_case=start_case)
        if dlg.exec() != QDialog.Accepted or dlg.model is None:
            return
        self.set_model(dlg.model, dirty=True)
        self.go(1)
        if dlg.run_after:
            self.run_current()

    def open_model(self, path: str | None = None):
        if path is None:
            if not self.maybe_save():
                return
            start = str(self.model.path.parent) if self.model.path else str(S.studio_dir() / "examples")
            path, _ = QFileDialog.getOpenFileName(self, "Open model", start,
                                                  f"PASCHEN-1D Studio models (*{MODEL_SUFFIX} *.json);;All files (*)")
            if not path:
                return
        try:
            m = StudioModel.load(path)
        except Exception as exc:
            QMessageBox.critical(self, "Open model", f"Could not open the model:\n{exc}")
            return
        if Path(path).name == "studio_model.p1d.json":
            m.path = None          # a run snapshot: saving should go to a new file
            m.title = (m.title or "Model") + " (from run)"
            self.set_model(m, dirty=True)
        else:
            self.set_model(m, dirty=False)
            self._add_recent(path)
        unk = getattr(m, "unknown_overrides", [])
        if unk:
            QMessageBox.warning(self, "Open model", "These settings are not part of the installed PASCHEN-1D "
                                "version and were ignored:\n" + "\n".join(unk))
        self.go(1)

    def _add_recent(self, path):
        items = [p for p in (self.settings.value("recent", []) or []) if p != str(path)]
        items.insert(0, str(path))
        self.settings.setValue("recent", items[:12])
        self._fill_recent()

    def save(self) -> bool:
        if self.model.path is None:
            return self.save_as()
        try:
            self.model.save()
        except OSError as exc:
            QMessageBox.critical(self, "Save", str(exc))
            return False
        self.dirty = False
        self._add_recent(self.model.path)
        self._update_header()
        self.statusBar().showMessage(f"Saved {self.model.path}", 4000)
        return True

    def save_as(self) -> bool:
        start = S.studio_dir() / "models"
        start.mkdir(exist_ok=True)
        name = (self.model.title or self.model.run_name).strip().replace(" ", "_").replace("/", "_") or "model"
        path, _ = QFileDialog.getSaveFileName(self, "Save model", str(start / f"{name}{MODEL_SUFFIX}"),
                                              f"PASCHEN-1D Studio model (*{MODEL_SUFFIX})")
        if not path:
            return False
        if not path.endswith(".json"):
            path += MODEL_SUFFIX
        self.model.path = Path(path)
        return self.save()

    def export_script(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Python run script",
                                              str(Path.home() / f"run_{self.model.run_name}.py"), "Python (*.py)")
        if path:
            Path(path).write_text(self.model.to_python_script(), encoding="utf-8")
            self.statusBar().showMessage(f"Wrote {path}", 5000)

    def import_case(self):
        path, _ = QFileDialog.getOpenFileName(self, "Case module defining SimulationConfig", str(Path.home()),
                                              "Python (*.py)")
        if not path:
            return
        p = Path(path)
        S.add_case_dir(p.parent)
        try:
            S.case_module(p.stem)
        except Exception as exc:
            QMessageBox.critical(self, "Import case", f"Could not import {p.name}:\n{exc}")
            return
        m = new_model_from_case(p.stem)
        m.base_case_dir = str(p.parent)
        self.set_model(m, dirty=True)
        self.go(1)

    def change_case(self):
        cases = S.list_cases()
        names = [f"{c.title}   ({c.module})" for c in cases]
        cur = next((i for i, c in enumerate(cases) if c.module == self.model.base_case), 0)
        item, ok = QInputDialog.getItem(self, "Change base case",
                                        "New base case (settings you changed are kept where possible):",
                                        names, cur, False)
        if not ok:
            return
        mod = cases[names.index(item)].module
        if mod != self.model.base_case:
            self.model.change_case(mod, keep_overrides=True)
            self.set_model(self.model, dirty=True)

    def reset_all(self):
        if QMessageBox.question(self, "Reset", "Reset every setting to the case defaults?") == QMessageBox.Yes:
            for p in list(self.model.overrides):
                self.model.reset(p)
            self.model_page.refresh_all()
            self._edited([])

    def undo(self):
        if self.model.undo():
            self.model_page.refresh_all()
            self._edited([])

    def redo(self):
        if self.model.redo():
            self.model_page.refresh_all()
            self._edited([])

    def find_setting(self):
        dlg = FindSettingDialog(self.model, self)
        if dlg.exec() and dlg.chosen:
            self.go(1)
            self.model_page.focus_setting(dlg.chosen)

    def ion_browser(self):
        dlg = IonBrowserDialog(self.model, self)
        if dlg.exec():
            ch = dlg.apply_to(self.model)
            if ch:
                self.model_page.after_edit(ch)

    def apply_fix(self, fix: str):
        ch = A.apply_fix(self.model, fix, self.workspace)
        if ch:
            self.model_page.after_edit(ch)
            self.statusBar().showMessage(f"Changed {len(ch)} setting(s): " + ", ".join(ch[:4]) +
                                         (" …" if len(ch) > 4 else ""), 6000)
        else:
            self.statusBar().showMessage("Nothing to change.", 3000)

    def check(self):
        self.go(1)
        issues = self.model_page.run_check(deep=True)
        ne = sum(1 for i in issues if i.level == "error")
        self.statusBar().showMessage("Model check passed." if ne == 0 else f"{ne} error(s) – see Model check.", 5000)

    # ======================================================================
    # running
    # ======================================================================
    def result_folders(self) -> list[Path]:
        out = [self.workspace]
        root = S.solver_root(required=False)
        if root:
            out.append(root)
        for f in (self.settings.value("result_folders", []) or []):
            if f and Path(f).is_dir():
                out.append(Path(f))
        return out

    def _resolve_run_name(self, name: str) -> str | None:
        if not (self.workspace / name).exists():
            return name
        box = QMessageBox(self)
        box.setWindowTitle("Run folder exists")
        box.setText(f"The workspace already contains a run named “{name}”.")
        box.setInformativeText("Overwriting deletes the old results. 'Keep both' runs into a new folder.")
        keep = box.addButton("Keep both", QMessageBox.AcceptRole)
        over = box.addButton("Overwrite", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(keep)
        box.exec()
        if box.clickedButton() is keep:
            return unique_run_name(name, self.workspace)
        if box.clickedButton() is over:
            if any(j.active and j.run_name == name for j in self.jobs.jobs):
                QMessageBox.warning(self, "Run", "That run is still in progress.")
                return None
            try:
                shutil.rmtree(self.workspace / name)
            except OSError as exc:
                QMessageBox.critical(self, "Run", str(exc))
                return None
            return name
        return None

    def run_current(self, test: bool = False, model: StudioModel | None = None, extra: dict | None = None,
                    label_suffix: str = ""):
        model = model or self.model
        issues = A.check_model(model, workspace=None, deep=True)
        errs = [i for i in issues if i.level == "error"]
        if errs:
            self.model_page.issues_panel.set_issues(issues)
            self.go(1)
            QMessageBox.warning(self, "Cannot run yet",
                                "The model check found problems:\n\n• " + "\n• ".join(e.message for e in errs[:6]) +
                                "\n\nFix them (many have a one-click fix in the Model check panel) and run again.")
            return None
        extra = dict(extra or {})
        name = model.run_name
        if test:
            v = model.values()
            Nt = int(v["numerics.Nt"])
            dt = float(v["run.T_total"]) / max(Nt - 1, 1)
            Nt2 = max(500, min(Nt, int(Nt * 0.02) + 1))
            extra.update({"numerics.Nt": Nt2, "run.T_total": dt * (Nt2 - 1),
                          "output.save_every": max(1, (Nt2 - 1) // 200)})
            name = f"{name}_test"
            label_suffix = label_suffix or " (test 2 %)"
        name = self._resolve_run_name(name)
        if name is None:
            return None
        job = self.jobs.enqueue(model, self.workspace, run_name=name, extra=extra,
                                label=model.display_title() + label_suffix)
        self.go(2)
        self.run_page.select_job(job)
        return job

    def demo_case(self, case: str):
        if not self.maybe_save():
            return
        m = new_model_from_case(case)
        m.title = m.title + " – demo"
        demo = DEMO_OVERRIDES.get(case)
        if demo:
            for k, val in demo.items():
                m.set(k, val, record=False)
            m.set("run.run_name", f"{m.run_name}_demo", record=False)
            self.set_model(m, dirty=True)
            self.run_current(label_suffix="")
        else:
            self.set_model(m, dirty=True)
            self.run_current(test=True, label_suffix=" (quick demo)")

    def sweep(self):
        from .sweep_dialog import SweepDialog
        dlg = SweepDialog(self.model, self)
        if dlg.exec() != QDialog.Accepted or not dlg.chosen:
            return
        r = dlg.chosen
        issues = A.check_model(self.model, deep=True)
        if any(i.level == "error" for i in issues):
            self.check()
            QMessageBox.warning(self, "Sweep", "Fix the model-check errors first.")
            return
        self.settings.setValue("max_concurrent", r["concurrent"])
        self.model.sweep = {"parameter": r["parameter"], "values": r["values"], "prefix": r["prefix"]}
        self.dirty = True
        jobs = sweep_jobs(self.model, r["parameter"], r["values"], r["prefix"])
        first = None
        for jd in jobs:
            name = unique_run_name(jd["run_name"], self.workspace)
            j = self.jobs.enqueue(self.model, self.workspace, run_name=name, extra=jd["extra"], label=jd["label"],
                                  sweep_info=jd["sweep_info"])
            first = first or j
        self.go(2)
        if first:
            self.run_page.select_job(first)

    def open_results(self, run_dir: str):
        self.go(3)
        self.results.open_run(run_dir)

    def _job_finished(self, job):
        msg = {"finished": "finished", "stopped": "stopped (results kept)", "failed": "FAILED",
               "aborted": "aborted"}.get(job.status, job.status)
        self.statusBar().showMessage(f"Run “{job.label}” {msg}.", 8000)
        if self.stack.currentIndex() == 3:
            self.results.refresh()
        QApplication.alert(self, 0)

    def _update_status(self):
        act = self.jobs.running()
        q = [j for j in self.jobs.jobs if j.status == "queued"]
        if act:
            self.run_dot.setText(str(len(act)))
            self.run_dot.show()
            j = act[0]
            self.s_jobs.setText(f"▶ {len(act)} running" + (f", {len(q)} queued" if q else "") +
                                f" · {j.label}: {100 * j.fraction:.1f} %" +
                                (f" · ETA {human_duration(j.eta)}" if j.eta else ""))
            self.s_prog.setValue(int(1000 * j.fraction))
            self.s_prog.show()
        else:
            self.run_dot.hide()
            self.s_jobs.setText(f"{len(q)} queued" if q else "")
            self.s_prog.hide()

    # ======================================================================
    # settings / theme
    # ======================================================================
    def choose_workspace(self):
        d = QFileDialog.getExistingDirectory(self, "Run workspace folder", str(self.workspace))
        if d:
            self.workspace = Path(d)
            self.settings.setValue("workspace", d)
            self.s_ws.setText(f"Workspace: {self.workspace}")
            self.model_page.workspace = self.workspace

    def preferences(self):
        old_theme = self.settings.value("theme", "light")
        dlg = PreferencesDialog(self.settings, self)
        if dlg.exec():
            ws = self.settings.value("workspace", "")
            if ws:
                self.workspace = Path(ws)
                self.workspace.mkdir(parents=True, exist_ok=True)
                self.s_ws.setText(f"Workspace: {self.workspace}")
                self.model_page.workspace = self.workspace
            self.run_page.timer.setInterval(int(self.settings.value("live_interval_ms", 1000)))
            if self.settings.value("theme", "light") != old_theme:
                self._apply_theme(self.settings.value("theme", "light"))
            self.jobs._pump()

    def toggle_theme(self):
        new = "dark" if T.current()["name"] == "light" else "light"
        self.settings.setValue("theme", new)
        self._apply_theme(new)

    def _apply_theme(self, name: str):
        from .app import apply_theme
        apply_theme(QApplication.instance(), name)
        idx = self.stack.currentIndex()
        old = self.centralWidget()
        jobs_sel = self.run_page.current
        self._build_ui()
        old.deleteLater()
        for j in self.jobs.jobs:
            self.run_page._added(j)
        if jobs_sel is not None:
            self.run_page.select_job(jobs_sel)
        self._build_menus()
        self.set_model(self.model, dirty=self.dirty)
        self.go(idx)

    def closeEvent(self, e):
        act = self.jobs.running()
        if act:
            r = QMessageBox.question(self, "Simulations running",
                                     f"{len(act)} simulation(s) are still running.\n\nStop them now? Results computed "
                                     "so far are kept (the solver writes its metadata).",
                                     QMessageBox.Yes | QMessageBox.Cancel)
            if r != QMessageBox.Yes:
                e.ignore()
                return
        if not self.maybe_save():
            e.ignore()
            return
        if act:
            self.jobs.shutdown()
        self.settings.setValue("geometry", self.saveGeometry())
        e.accept()
