"""In-app help: quick start, studio guide, the solver's own tutorial/README, shortcuts, citation."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QListWidget, QListWidgetItem, QTextBrowser, QVBoxLayout,
                               QWidget)

from .. import BIBTEX, PAPER_AUTHORS, PAPER_JOURNAL, PAPER_TITLE, PAPER_URL, REPO_URL, ARXIV_URL
from .. import solver as S
from . import icons
from . import theme as T
from .builder import pane
from .widgets import label, push

QUICKSTART = """
# Quick start

**PASCHEN-1D Studio** is a graphical front end for the PASCHEN-1D drift-diffusion–Poisson solver.
You never have to edit Python files: every setting of the solver is available in forms.

## 1 · Create a model
* **Home → New simulation – guided** walks you through gas, gap, voltage, circuit, emission and resolution.
* Or open one of the **validated cases** (nitrogen DBD, argon DC glow, argon/helium photoemission,
  deuterium DBD) and change only what you need.
* A *model* = a base case + the settings you changed. It is saved as a small `*.p1d.json` file.

## 2 · Edit settings
* The **Model Builder** tree groups the solver's 18 configuration blocks.
* Type values with units: `3.5 mm`, `16 pF`, `70 us`, `0.4 MOhm`, `inf`. Hover any field for the solver's
  own explanation; the ↺ button restores the case default.
* Settings that do not apply to your current choices are hidden (toggle **Inactive** to see them).
* **Ctrl+K** finds any setting by name or meaning.
* The **Preview** shows the gap, the circuit diagram, V_app(t), a classical Paschen breakdown estimate and
  the transport coefficients – all computed with the solver's own functions.

## 3 · Check
The **Model check** runs PASCHEN-1D's `validate_simulation_config` and adds advice (run time, disk space,
stability, gas/closure consistency). Many problems have a one-click **fix** button.

## 4 · Run
* **F5** runs the model; **Quick test run** runs 2 % of the time steps with the same dt.
* Runs are queued; each is a separate process, so the interface never freezes.
* **Pause**, **Stop & keep results** (the solver still writes its metadata) or **Abort**.
* The **live monitor** shows profiles and histories while the solver works.

## 5 · Analyse
* **Results** lists Studio runs *and* runs made with the notebooks.
* Summary metrics, time histories, snapshot profiles with a time slider and animation, space–time maps,
  time-averaged profiles, run comparison and parameter-sweep summaries.
* Every plot: zoom (mouse wheel), pan, log scale, **publication export** (PNG/PDF/SVG/EPS at any size and DPI)
  and CSV export.

## Command line
```
python -m paschen_studio gui                       # this application
python -m paschen_studio run   model.p1d.json      # run a model in the terminal
python -m paschen_studio sweep model.p1d.json      # run the sweep stored in a model
python -m paschen_studio check model.p1d.json      # validate a model
python -m paschen_studio cases                     # list solver cases
python -m paschen_studio new   CASE  out.p1d.json  # new model file from a case
python -m paschen_studio export-script model.p1d.json run.py
python -m paschen_studio info                      # versions and paths
```
"""

SHORTCUTS = """
# Keyboard shortcuts

| Action | Shortcut |
|---|---|
| New simulation (wizard) | Ctrl+N |
| Open model | Ctrl+O |
| Save model | Ctrl+S |
| Save model as | Ctrl+Shift+S |
| Undo / Redo a setting change | Ctrl+Z / Ctrl+Shift+Z |
| Find a setting | Ctrl+K |
| Check model | Ctrl+Shift+K |
| Run | F5 |
| Quick test run | Shift+F5 |
| Home / Model / Simulation / Results / Help | Ctrl+1 … Ctrl+5 |
| Toggle dark theme | Ctrl+Shift+D |

On macOS use ⌘ instead of Ctrl. In plots: mouse wheel = zoom, double-click = reset view, right-click = export menu.
"""


class HelpPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        left, lv, _, _ = pane("Help")
        self.list = QListWidget()
        lv.addWidget(self.list, 1)
        left.setFixedWidth(250)
        root.addWidget(left)
        right = QFrame()
        right.setObjectName("pane")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(24, 16, 24, 16)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        rv.addWidget(self.browser, 1)
        self.action_bar = QHBoxLayout()
        rv.addLayout(self.action_bar)
        root.addWidget(right, 1)
        self.pages = {}
        studio_docs = S.studio_dir() / "docs"
        root_dir = S.solver_root()
        entries = [("quickstart", "Quick start", "help", QUICKSTART),
                   ("guide", "Studio user guide", "book", studio_docs / "USER_GUIDE.md"),
                   ("tutorial", "PASCHEN-1D tutorial", "book", root_dir / "TUTORIAL.md"),
                   ("readme", "PASCHEN-1D README", "info", root_dir / "README.md"),
                   ("ions", "Ion-transport validation", "ion", root_dir / "ION_TRANSPORT_VALIDATION.md"),
                   ("shortcuts", "Keyboard shortcuts", "settings", SHORTCUTS),
                   ("cite", "Cite PASCHEN-1D", "quote", None)]
        for key, title, ic, src in entries:
            if isinstance(src, Path) and not src.exists():
                continue
            it = QListWidgetItem(icons.icon(ic, T.c("accent"), 16), title)
            it.setData(Qt.UserRole, key)
            self.list.addItem(it)
            self.pages[key] = src
        self.list.currentRowChanged.connect(self._show)
        self.list.setCurrentRow(0)

    def show_page(self, key: str):
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == key:
                self.list.setCurrentRow(i)
                return

    def _show(self, row):
        it = self.list.item(row)
        if it is None:
            return
        key = it.data(Qt.UserRole)
        src = self.pages[key]
        while self.action_bar.count():
            w = self.action_bar.takeAt(0).widget()
            if w:
                w.deleteLater()
        if key == "cite":
            md = (f"# Cite PASCHEN-1D\n\nIf you use PASCHEN-1D (and this studio) in published work, please cite\n\n"
                  f"> {PAPER_AUTHORS}, “{PAPER_TITLE}”, *{PAPER_JOURNAL}*.\n\n"
                  f"* Journal article: <{PAPER_URL}>\n* arXiv preprint: <{ARXIV_URL}>\n* Source code: <{REPO_URL}>\n\n"
                  f"```\n{BIBTEX}\n```\n")
            self.browser.setMarkdown(md)
            b = push("Copy BibTeX", "primary", icon_name="copy")
            b.clicked.connect(lambda: QGuiApplication.clipboard().setText(BIBTEX))
            self.action_bar.addWidget(b)
            b2 = push("Open paper", icon_name="external")
            b2.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PAPER_URL)))
            self.action_bar.addWidget(b2)
            self.action_bar.addStretch()
            return
        if isinstance(src, Path):
            text = src.read_text(encoding="utf-8", errors="replace")
            self.browser.setSearchPaths([str(src.parent)])
            self.browser.setMarkdown(text)
            b = push("Open file", icon_name="external")
            b.clicked.connect(lambda _=None, p=src: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))))
            self.action_bar.addWidget(b)
            self.action_bar.addWidget(label(str(src), "hint"))
            self.action_bar.addStretch()
        else:
            self.browser.setMarkdown(src)
