"""Dialogs: ion-data library, setting finder, preferences, about/cite."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QSpinBox, QSplitter,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from .. import (APP_NAME, ARXIV_URL, BIBTEX, PAPER_AUTHORS, PAPER_JOURNAL, PAPER_TITLE, PAPER_URL, REPO_URL,
                __version__)
from .. import advisor as A
from .. import schema as SC
from .. import solver as S
from . import icons
from . import theme as T
from .plotting import AxesSpec, FigureSpec, PlotCanvas, Series
from .widgets import label, push


# ---------------------------------------------------------------------------
class IonBrowserDialog(QDialog):
    """Browse the bundled LXCat positive-ion transport library and pick a dataset."""

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.choice = None
        self.setWindowTitle("Ion transport library (LXCat, normalized)")
        self.resize(1080, 620)
        v = QVBoxLayout(self)
        v.addWidget(label("Ion transport library", "h3"))
        v.addWidget(label("Each entry is an independent LXCat dataset for a positive ion drifting through a neutral "
                          "gas. Matched pairs provide both mobility and longitudinal diffusion; mobility-only "
                          "entries use the Einstein relation for diffusion. The gas temperature must match Tᵢ.",
                          "muted", wrap=True))
        top = QHBoxLayout()
        self.gas = QComboBox()
        self.gas.setEditable(True)
        for g, disp in S.known_gases():
            self.gas.addItem(disp, g)
        self.gas.setCurrentText(str(model.value("plasma_state.gas")))
        self.native = QCheckBox("Only the gas's own ions")
        self.native.setChecked(True)
        self.pairs_only = QCheckBox("Matched pairs only")
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter ion / database / reference…")
        top.addWidget(QLabel("Neutral gas"))
        top.addWidget(self.gas)
        top.addWidget(self.native)
        top.addWidget(self.pairs_only)
        top.addWidget(self.filter, 1)
        v.addLayout(top)
        sp = QSplitter(Qt.Horizontal)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Kind", "Ion", "Neutral", "T [K]", "E/N range [Td]", "Database",
                                              "Reference"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._preview)
        self.table.doubleClicked.connect(lambda _: self._accept())
        sp.addWidget(self.table)
        self.plot = PlotCanvas("", log_toggle=False, export_name="ion_table")
        sp.addWidget(self.plot)
        sp.setSizes([680, 380])
        v.addWidget(sp, 1)
        self.info = label("", "hint", wrap=True)
        v.addWidget(self.info)
        bb = QDialogButtonBox()
        self.use = bb.addButton("Use this dataset", QDialogButtonBox.AcceptRole)
        self.use.setObjectName("primary")
        bb.addButton(QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        for w in (self.gas,):
            w.currentTextChanged.connect(lambda _: self._fill())
        self.native.toggled.connect(lambda _: self._fill())
        self.pairs_only.toggled.connect(lambda _: self._fill())
        self.filter.textChanged.connect(lambda _: self._fill())
        self._rows = []
        self._fill()

    def _gas(self) -> str:
        t = self.gas.currentText().strip()
        for i in range(self.gas.count()):
            if self.gas.itemText(i) == t:
                return self.gas.itemData(i)
        return t

    def _fill(self):
        gas = self._gas()
        rows = []
        for p in S.ion_pairs_for_gas(gas):
            rows.append(dict(kind="pair", ion=p["ion"], neutral=p["neutral"], T=p.get("gas_temperature_K"),
                             lo=p.get("common_reduced_field_min_Td"), hi=p.get("common_reduced_field_max_Td"),
                             db=p.get("database", ""), ref=p.get("reference", ""),
                             mobility=Path(p["mobility_file"]).name, diffusion=Path(p["diffusion_file"]).name))
        if not self.pairs_only.isChecked():
            for r in S.ion_mobility_tables_for_gas(gas):
                rows.append(dict(kind="mobility + Einstein", ion=r["ion"], neutral=r["neutral"],
                                 T=r.get("gas_temperature_K"), lo=r.get("axis_min"), hi=r.get("axis_max"),
                                 db=r.get("database", ""), ref=r.get("reference", ""),
                                 mobility=Path(r["normalized_file"]).name, diffusion=None))
        if self.native.isChecked():
            rows = [r for r in rows if S.ion_is_native(r["ion"], r["neutral"])]
        f = self.filter.text().strip().lower()
        if f:
            rows = [r for r in rows if f in f"{r['ion']} {r['db']} {r['ref']}".lower()]
        self._rows = rows
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [r["kind"], str(r["ion"]).replace("^", ""), r["neutral"], f"{float(r['T'] or 0):g}",
                    f"{float(r['lo'] or 0):.3g} – {float(r['hi'] or 0):.3g}", r["db"], r["ref"]]
            for j, val in enumerate(vals):
                it = QTableWidgetItem(str(val))
                it.setToolTip(str(val))
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(6, 300)
        self.info.setText(f"{len(rows)} datasets for '{gas}'. Tᵢ = {self.model.value('plasma_state.T_i')} K.")
        if rows:
            self.table.selectRow(0)

    def _sel(self):
        i = self.table.currentRow()
        return self._rows[i] if 0 <= i < len(self._rows) else None

    def _preview(self):
        r = self._sel()
        if r is None:
            return
        ax = AxesSpec(title=f"{str(r['ion']).replace('^', '')} in {r['neutral']}", xlabel="E/N [Td]",
                      ylabel="reduced transport (SI)", xscale="log", yscale="log")
        for key, lab, col in (("mobility", "K₀N₀ (mobility)", T.c("role")["ion"]),
                              ("diffusion", "N·D_L (diffusion)", T.c("role")["electron"])):
            if r.get(key):
                res = A.ion_table_preview(r[key])
                if res:
                    ax.series.append(Series(res[0], res[1], label=lab, color=col, marker="o"))
        self.plot.set_spec(FigureSpec([ax]), keep_view=False)

    def _accept(self):
        r = self._sel()
        if r is None:
            return
        self.choice = r
        self.accept()

    def apply_to(self, model) -> list[str]:
        r = self.choice
        if r is None:
            return []
        changed = []
        sets = [("plasma.ion_kinetics_model", "local_field_ion_kinetics"),
                ("ion_transport.positive_ion", str(r["ion"]).replace("^", "")),
                ("ion_transport.mobility_source_mode", "swarm_data_table_interpolation"),
                ("ion_transport.diffusion_source_mode",
                 "swarm_data_table_interpolation" if r["diffusion"] else "einstein_relation"),
                ("ion_transport.mobility_table_path", r["mobility"]),
                ("ion_transport.diffusion_table_path", r["diffusion"])]
        for p, val in sets:
            if model.set(p, val):
                changed.append(p)
        return changed


# ---------------------------------------------------------------------------
class FindSettingDialog(QDialog):
    """Command-palette style search across every solver setting."""

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.chosen = None
        self.setWindowTitle("Find a setting")
        self.resize(680, 460)
        v = QVBoxLayout(self)
        self.q = QLineEdit()
        self.q.setPlaceholderText("Type to search every setting: e.g. pressure, laser, R0, gamma, snapshot…")
        self.q.addAction(icons.icon("search", T.c("text3"), 16), QLineEdit.LeadingPosition)
        v.addWidget(self.q)
        self.list = QListWidget()
        v.addWidget(self.list, 1)
        v.addWidget(label("↑/↓ to choose · Enter to open · settings that are not used right now are dimmed", "hint"))
        self.q.textChanged.connect(self._search)
        self.q.returnPressed.connect(self._accept)
        self.list.itemActivated.connect(lambda _: self._accept())
        self._index = []
        schema = model.schema
        for p, fi in schema.fields.items():
            self._index.append((p, SC.search_text(p, fi.comment)))
        self._search("")

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Down, Qt.Key_Up) and self.q.hasFocus():
            r = self.list.currentRow() + (1 if e.key() == Qt.Key_Down else -1)
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, r)))
            return
        super().keyPressEvent(e)

    def _search(self, text):
        self.list.clear()
        vals = self.model.values()
        if text.strip():
            scored = [(SC.match_score(text, t), p) for p, t in self._index]
            scored = [x for x in scored if x[0] > 0.5]
            scored.sort(key=lambda x: -x[0])
            paths = [p for _, p in scored[:60]]
        else:
            paths = [p for p, _ in self._index if self.model.is_modified(p)] or \
                    [p for p, _ in self._index][:40]
        for p in paths:
            fi = self.model.schema.fields[p]
            meta = SC.meta_for(p, fi.comment)
            g = p.rpartition(".")[0]
            active, _ = SC.field_active(p, vals)
            it = QListWidgetItem(f"{meta.label}    —  {SC.GROUP_TITLES.get(g, g)}    ({p})")
            it.setData(Qt.UserRole, p)
            it.setIcon(icons.icon(SC.GROUP_ICONS.get(g, "dot"), T.c("accent") if active else T.c("text3"), 16))
            if not active:
                it.setForeground(Qt.gray)
            it.setToolTip(fi.comment or p)
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _accept(self):
        it = self.list.currentItem()
        if it is not None:
            self.chosen = it.data(Qt.UserRole)
            self.accept()


# ---------------------------------------------------------------------------
class PreferencesDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.s = settings
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(620)
        v = QVBoxLayout(self)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        self.theme = QComboBox()
        self.theme.addItem("Light", "light")
        self.theme.addItem("Dark", "dark")
        self.theme.setCurrentIndex(0 if settings.value("theme", "light") == "light" else 1)
        form.addRow("Theme", self.theme)
        self.ws = QLineEdit(str(settings.value("workspace", "")))
        b = QPushButton("Choose…")
        b.clicked.connect(lambda: self._pick(self.ws))
        h = QHBoxLayout()
        h.addWidget(self.ws, 1)
        h.addWidget(b)
        form.addRow("Run workspace folder", h)
        self.root = QLineEdit(str(settings.value("solver_root", S.solver_root(required=False) or "")))
        b2 = QPushButton("Choose…")
        b2.clicked.connect(lambda: self._pick(self.root))
        h2 = QHBoxLayout()
        h2.addWidget(self.root, 1)
        h2.addWidget(b2)
        form.addRow("PASCHEN-1D folder", h2)
        self.extra = QPlainTextEdit("\n".join(settings.value("result_folders", []) or []))
        self.extra.setObjectName("input")
        self.extra.setMaximumHeight(80)
        self.extra.setPlaceholderText("One folder per line (runs made with the notebooks, other workspaces…)")
        form.addRow("Extra results folders", self.extra)
        self.conc = QSpinBox()
        self.conc.setRange(1, 64)
        self.conc.setValue(int(settings.value("max_concurrent", 1)))
        self.conc.setToolTip("How many simulations may run at the same time (each uses one CPU core).")
        form.addRow("Simultaneous runs", self.conc)
        self.autocheck = QCheckBox("Check the model automatically while editing")
        self.autocheck.setChecked(str(settings.value("auto_check", "true")).lower() == "true")
        form.addRow("", self.autocheck)
        self.live = QSpinBox()
        self.live.setRange(250, 10000)
        self.live.setSingleStep(250)
        self.live.setSuffix(" ms")
        self.live.setValue(int(settings.value("live_interval_ms", 1000)))
        form.addRow("Live plot refresh", self.live)
        v.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _pick(self, le: QLineEdit):
        d = QFileDialog.getExistingDirectory(self, "Choose folder", le.text() or str(Path.home()))
        if d:
            le.setText(d)

    def _save(self):
        s = self.s
        s.setValue("theme", self.theme.currentData())
        if self.ws.text().strip():
            s.setValue("workspace", self.ws.text().strip())
        root = self.root.text().strip()
        if root and S.is_solver_root(root):
            s.setValue("solver_root", root)
        s.setValue("result_folders", [ln.strip() for ln in self.extra.toPlainText().splitlines() if ln.strip()])
        s.setValue("max_concurrent", self.conc.value())
        s.setValue("auto_check", "true" if self.autocheck.isChecked() else "false")
        s.setValue("live_interval_ms", self.live.value())
        self.accept()


# ---------------------------------------------------------------------------
class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setMinimumWidth(680)
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        lg = QLabel()
        lg.setPixmap(icons.logo_pixmap(72))
        top.addWidget(lg)
        tv = QVBoxLayout()
        tv.addWidget(label(APP_NAME, "h2"))
        sv, sd = S.solver_version()
        tv.addWidget(label(f"Studio {__version__}  ·  PASCHEN-1D solver {sv} ({sd})", "muted"))
        tv.addWidget(label(f"Solver folder: {S.solver_root(required=False)}", "hint", selectable=True))
        top.addLayout(tv, 1)
        v.addLayout(top)
        v.addSpacing(6)
        v.addWidget(label("If you use PASCHEN-1D, please cite:", "h3"))
        v.addWidget(label(f"{PAPER_AUTHORS}, “{PAPER_TITLE}”, {PAPER_JOURNAL}.", wrap=True, selectable=True))
        bib = QPlainTextEdit(BIBTEX)
        bib.setReadOnly(True)
        bib.setObjectName("console")
        bib.setLineWrapMode(QPlainTextEdit.NoWrap)      # BibTeX keeps its layout; long lines scroll in the box
        bib.ensurePolished()
        n_lines = BIBTEX.strip("\n").count("\n") + 1
        bib.setFixedHeight(int(bib.fontMetrics().lineSpacing() * n_lines + 2 * bib.document().documentMargin()
                               + bib.frameWidth() * 2 + 30))
        v.addWidget(bib)
        h = QHBoxLayout()
        for text, url, ic in (("Paper", PAPER_URL, "book"), ("arXiv", ARXIV_URL, "external"),
                              ("GitHub", REPO_URL, "github")):
            b = push(text, icon_name=ic)
            b.clicked.connect(lambda _=None, u=url: QDesktopServices.openUrl(QUrl(u)))
            h.addWidget(b)
        cp = push("Copy BibTeX", icon_name="copy")
        cp.clicked.connect(lambda: QGuiApplication.clipboard().setText(BIBTEX))
        h.addWidget(cp)
        h.addStretch()
        close = push("Close", "primary")
        close.clicked.connect(self.accept)
        h.addWidget(close)
        v.addLayout(h)
        v.addWidget(label("PASCHEN-1D Studio is an add-on graphical interface: it reads the solver's configuration "
                          "classes and calls its public API. It never modifies the solver's source files. "
                          "License: same terms as PASCHEN-1D (no commercial use without permission).",
                          "hint", wrap=True))
