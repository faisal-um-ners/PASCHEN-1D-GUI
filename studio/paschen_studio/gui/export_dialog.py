"""Publication export with a live preview.

Everything starts from the plot on screen (its labels, legend entries, axis scales and the axis limits
currently shown) and can be edited: page size and format, font family and size (including LaTeX
typesetting), axis labels with $…$ math, legend on/off, position, columns and entry texts, linear/log
axes and axis limits.
"""
from __future__ import annotations

import copy
import io
import math
import re
import shutil
from dataclasses import dataclass, field

import matplotlib
from matplotlib.figure import Figure
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QTabWidget,
                               QVBoxLayout, QWidget)

from . import theme as T
from .plotting import FigureSpec, render
from .widgets import label, push

FORMATS = [("PNG (raster)", "png"), ("PDF (vector)", "pdf"), ("SVG (vector)", "svg"), ("EPS (vector)", "eps"),
           ("TIFF (raster)", "tiff")]
STYLES = [("Publication – white", "publication"), ("Presentation – dark", "dark"), ("Same as screen", "screen")]
PRESETS = [("Single column (3.4 × 2.6 in)", 3.4, 2.6), ("Double column (7.0 × 3.6 in)", 7.0, 3.6),
           ("Slide (10 × 5.6 in)", 10.0, 5.6), ("Square (4 × 4 in)", 4.0, 4.0), ("Custom", None, None)]
FAMILIES = [("Sans-serif (Arial / Helvetica)", "sans"), ("Serif (Times)", "serif"),
            ("LaTeX look (Computer Modern)", "cm"), ("STIX (Times-like, rich math)", "stix"),
            ("DejaVu Sans (Matplotlib default)", "dejavu")]
LEGEND_POS = [("Automatic (best place)", "best", None), ("Upper right", "upper right", None),
              ("Upper left", "upper left", None), ("Lower right", "lower right", None),
              ("Lower left", "lower left", None), ("Center right", "center right", None),
              ("Center left", "center left", None), ("Upper center", "upper center", None),
              ("Lower center", "lower center", None), ("Center", "center", None),
              ("Outside, right of the plot", "center left", (1.02, 0.5)),
              ("Outside, above the plot", "lower center", (0.5, 1.02))]
SCALES = [("Linear", "linear"), ("Logarithmic", "log")]
MATH_HINT = ("Labels accept LaTeX math between dollar signs, e.g. <code>$V_\\mathrm{gap}$ (kV)</code>, "
             "<code>$n_e$ [m$^{-3}$]</code>, <code>$E/N$ (Td)</code>.")


# ---------------------------------------------------------------------------
# options
@dataclass
class PanelOpts:
    title: str = ""
    xlabel: str = ""
    ylabel: str = ""
    ylabel2: str | None = None
    xscale: str = "linear"
    yscale: str = "linear"
    xlim: tuple = (None, None)
    ylim: tuple = (None, None)
    legend: bool = True
    labels: list = field(default_factory=list)


@dataclass
class ExportOptions:
    fmt: str = "png"
    style: str = "publication"
    w: float = 3.4
    h: float = 2.6
    dpi: int = 600
    font_size: float = 9.0
    family: str = "sans"
    usetex: bool = False
    line_width: float = 1.5
    ticks: str = "in"
    grid: bool = False
    titles: bool = False
    legend_pos: int = 0
    legend_ncol: int = 1
    legend_frame: bool = False
    legend_scale: float = 0.85
    panels: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# text helpers
_SUP = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
        "⁻": "-", "⁺": "+"}
_SUB = {"₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
        "ₑ": "e", "ᵢ": "i", "ₐ": "a", "ₒ": "o", "ₓ": "x", "ₙ": "n", "ₘ": "m", "ₚ": "p", "ₛ": "s", "ₜ": "t",
        "ₖ": "k", "ₗ": "l", "ₕ": "h", "₊": "+", "₋": "-"}
_GREEK = {"α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta", "ε": r"\varepsilon", "ζ": r"\zeta",
          "η": r"\eta", "θ": r"\theta", "κ": r"\kappa", "λ": r"\lambda", "μ": r"\mu", "µ": r"\mu", "ν": r"\nu",
          "ξ": r"\xi", "π": r"\pi", "ρ": r"\rho", "σ": r"\sigma", "τ": r"\tau", "φ": r"\varphi", "χ": r"\chi",
          "ψ": r"\psi", "ω": r"\omega", "Γ": r"\Gamma", "Δ": r"\Delta", "Θ": r"\Theta", "Λ": r"\Lambda",
          "Σ": r"\Sigma", "Φ": r"\Phi", "Ψ": r"\Psi", "Ω": r"\Omega"}
_SYMBOLS = {"·": r"\cdot", "×": r"\times", "≈": r"\approx", "→": r"\rightarrow", "≤": r"\leq", "≥": r"\geq",
            "°": r"^\circ", "−": "-"}
_LETTER = "A-Za-z" + "".join(k for k in _GREEK if len(k) == 1)


def to_mathtext(s: str) -> str:
    """Turn the plot's plain labels into LaTeX-style math so they typeset well and are easy to edit:
    ``V_gap`` → ``$V_\\mathrm{gap}$``, ``nₑ`` → ``$n_\\mathrm{e}$``, ``m⁻³`` → ``m$^{-3}$``."""
    if not s or "$" in s:
        return s or ""
    s = re.sub("[" + "".join(_SUP) + "]+", lambda m: "$^{" + "".join(_SUP[c] for c in m.group()) + "}$", s)
    s = re.sub(f"([{_LETTER}])([" + "".join(_SUB) + "]+)",
               lambda m: f"${m.group(1)}_\\mathrm{{{''.join(_SUB[c] for c in m.group(2))}}}$", s)
    s = re.sub(rf"(?<![\w$\\])([{_LETTER}])_([A-Za-z0-9]+)(?![\w])",
               lambda m: f"${m.group(1)}_\\mathrm{{{m.group(2)}}}$", s)
    return s.replace("$$", "")            # merge neighbouring math pieces


def tex_safe(s: str) -> str:
    """Make a label valid for real LaTeX (text.usetex): escape special characters outside math and
    replace Unicode Greek letters/symbols with LaTeX commands."""
    if not s:
        return s
    parts = s.split("$")
    if len(parts) % 2 == 0:                    # unbalanced $: leave it, the preview shows the error
        return s
    out = []
    for i, p in enumerate(parts):
        if i % 2 == 0:
            p = re.sub(r"(?<!\\)([_%&#])", r"\\\1", p)
            for ch, cmd in {**_GREEK, **_SYMBOLS}.items():
                if ch in p:
                    p = p.replace(ch, f"${cmd}$" if ch != "−" else "-")
            p = p.replace("–", "--").replace("—", "---")
        else:
            for ch, cmd in {**_GREEK, **_SYMBOLS}.items():
                p = p.replace(ch, cmd + " " if cmd.startswith("\\") else cmd)
        out.append(p)
    return "$".join(out).replace("$$", "")      # merge neighbouring math pieces ($$ would be display math)


def latex_available() -> bool:
    return bool(shutil.which("latex") and shutil.which("dvipng"))


# ---------------------------------------------------------------------------
# rendering
def defaults_from_spec(spec: FigureSpec, view=None) -> list[PanelOpts]:
    """Panel options pre-filled from the plot on screen (labels, legend texts, scales, visible limits)."""
    panels = []
    for i, a in enumerate(spec.axes):
        ser = list(a.series) + (list(a.twin.series) if a.twin is not None else [])
        p = PanelOpts(title=a.title, xlabel=to_mathtext(a.xlabel), ylabel=to_mathtext(a.ylabel),
                      ylabel2=to_mathtext(a.twin.ylabel) if a.twin is not None else None,
                      xscale=a.xscale if a.xscale in ("linear", "log") else "linear",
                      yscale=a.yscale if a.yscale in ("linear", "log") else "linear",
                      legend=a.legend, labels=[to_mathtext(s.label) for s in ser])
        if view is not None and i < len(view) and view[i] is not None:
            (x0, x1), (y0, y1) = view[i]
            p.xlim, p.ylim = (x0, x1), (y0, y1)
        panels.append(p)
    return panels


def build_spec(spec: FigureSpec, opts: ExportOptions) -> FigureSpec:
    s = copy.deepcopy(spec)
    for a, p in zip(s.axes, opts.panels):
        a.title = p.title if opts.titles else ""
        a.xlabel, a.ylabel = p.xlabel, p.ylabel
        if a.twin is not None and p.ylabel2 is not None:
            a.twin.ylabel = p.ylabel2
        a.xscale, a.yscale = p.xscale, p.yscale
        a.xlim = tuple(p.xlim) if any(v is not None for v in p.xlim) else None
        a.ylim = tuple(p.ylim) if any(v is not None for v in p.ylim) else None
        a.legend = p.legend
        ser = list(a.series) + (list(a.twin.series) if a.twin is not None else [])
        for se, lab in zip(ser, p.labels):
            se.label = lab
    if not opts.titles:
        s.suptitle = ""
    if opts.usetex:
        s.suptitle = tex_safe(s.suptitle)
        for a in s.axes:
            for obj in [a] + ([a.twin] if a.twin is not None else []):
                obj.title, obj.xlabel, obj.ylabel = tex_safe(obj.title), tex_safe(obj.xlabel), tex_safe(obj.ylabel)
                for se in obj.series:
                    se.label = tex_safe(se.label)
            for m in a.marks:
                m.text = tex_safe(m.text)
            if a.image is not None:
                a.image.clabel = tex_safe(a.image.clabel)
    return s


def _family_rc(key: str, usetex: bool) -> dict:
    if usetex:
        return {"text.usetex": True, "font.family": "sans-serif" if key in ("sans", "dejavu") else "serif",
                "text.latex.preamble": r"\usepackage{amsmath}"}
    if key == "sans":
        fam = T.mpl_font_family(("Arial", "Helvetica", "Liberation Sans", "Nimbus Sans", "DejaVu Sans"))
        return {"font.family": fam, "mathtext.fontset": "custom", "mathtext.rm": fam[0],
                "mathtext.it": f"{fam[0]}:italic", "mathtext.bf": f"{fam[0]}:bold", "mathtext.sf": fam[0],
                "mathtext.cal": fam[0], "mathtext.fallback": "stixsans"}
    if key == "serif":
        fam = T.mpl_font_family(("Times New Roman", "Times", "Nimbus Roman", "TeX Gyre Termes", "Liberation Serif",
                                 "DejaVu Serif"))
        return {"font.family": fam, "mathtext.fontset": "stix"}
    if key == "cm":
        return {"font.family": ["cmr10", "DejaVu Serif"], "mathtext.fontset": "cm", "axes.formatter.use_mathtext": True}
    if key == "stix":
        return {"font.family": ["STIXGeneral", "DejaVu Serif"], "mathtext.fontset": "stix"}
    return {"font.family": ["DejaVu Sans"], "mathtext.fontset": "dejavusans"}


def export_rc(opts: ExportOptions) -> dict:
    if opts.style == "screen":
        rc = {}
    else:
        rc = T.publication_rc(opts.font_size, dark=(opts.style == "dark"))
    fs = opts.font_size
    rc.update({"font.size": fs, "axes.labelsize": fs, "axes.titlesize": fs, "xtick.labelsize": fs * 0.9,
               "ytick.labelsize": fs * 0.9, "legend.fontsize": fs * opts.legend_scale,
               "legend.frameon": opts.legend_frame, "lines.linewidth": opts.line_width,
               "xtick.direction": opts.ticks, "ytick.direction": opts.ticks, "axes.grid": opts.grid,
               "grid.alpha": 0.35, "grid.linewidth": 0.6})
    rc.update(_family_rc(opts.family, opts.usetex))
    return rc


def _legend_opts(opts: ExportOptions) -> dict:
    _, loc, bbox = LEGEND_POS[max(0, min(opts.legend_pos, len(LEGEND_POS) - 1))]
    lo = {"loc": loc, "ncol": opts.legend_ncol, "frameon": opts.legend_frame}
    if bbox is not None:
        lo["bbox"] = bbox
    return lo


def _draw(spec: FigureSpec, opts: ExportOptions, dpi: float, sink):
    spec2 = build_spec(spec, opts)
    with matplotlib.rc_context(export_rc(opts)):
        fig = Figure(figsize=(opts.w, opts.h), dpi=dpi)
        if opts.style == "screen":
            render(fig, spec2, publication=False, colors=T.c("series"), legend_opts=_legend_opts(opts))
        else:
            render(fig, spec2, publication=True, colors=matplotlib.rcParams["axes.prop_cycle"].by_key()["color"],
                   legend_opts=_legend_opts(opts))
        return sink(fig)


def export_figure(spec: FigureSpec, opts: ExportOptions, path: str) -> str:
    def save(fig):
        kw = {"dpi": opts.dpi, "bbox_inches": "tight", "pad_inches": 0.03}
        if opts.style == "screen":
            kw["facecolor"] = fig.get_facecolor()
        fig.savefig(path, **kw)
        return path
    return _draw(spec, opts, opts.dpi, save)


def preview_png(spec: FigureSpec, opts: ExportOptions, dpi: float) -> bytes:
    def save(fig):
        buf = io.BytesIO()
        kw = {"format": "png", "dpi": dpi, "bbox_inches": "tight", "pad_inches": 0.03}
        if opts.style == "screen":
            kw["facecolor"] = fig.get_facecolor()
        fig.savefig(buf, **kw)
        return buf.getvalue()
    return _draw(spec, opts, dpi, save)


# ---------------------------------------------------------------------------
def _fmt_lim(v) -> str:
    return "" if v is None else f"{v:.4g}"


class _LimitEdit(QLineEdit):
    """Axis limit: a number, or empty for automatic."""

    def __init__(self, placeholder: str):
        super().__init__()
        self.setPlaceholderText(placeholder)
        self.textChanged.connect(self._validate)

    def value(self):
        t = self.text().strip().replace("−", "-")
        if not t:
            return None
        try:
            v = float(t)
            return v if math.isfinite(v) else None
        except ValueError:
            return None

    def ok(self) -> bool:
        return not self.text().strip() or self.value() is not None

    def _validate(self):
        self.setProperty("invalid", not self.ok())
        self.style().unpolish(self)
        self.style().polish(self)


class ExportDialog(QDialog):
    """Export settings (left) with a live preview of the exported figure (right)."""

    def __init__(self, parent, spec: FigureSpec, view=None, default_name: str = "figure"):
        super().__init__(parent)
        self.setWindowTitle("Export figure")
        self.spec = spec
        self.default_name = default_name
        self.defaults = defaults_from_spec(spec, view)
        self.panels = copy.deepcopy(self.defaults)
        self.cur = 0
        self._loading = False
        self.settings = QSettings()
        self.resize(1120, 700)
        root = QHBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)

        # ---------------- settings ----------------
        left = QWidget()
        left.setFixedWidth(420)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)
        lv.addWidget(label("Export figure", "h3"))
        lv.addWidget(label("Everything starts from the plot on screen and can be edited here.", "muted", wrap=True))
        prow = QHBoxLayout()
        self.panel_lab = label("Panel", "muted")
        self.panel_combo = QComboBox()
        for i, a in enumerate(spec.axes):
            name = a.title or a.ylabel or f"Panel {i + 1}"
            self.panel_combo.addItem(f"{i + 1} · {name}")
        prow.addWidget(self.panel_lab)
        prow.addWidget(self.panel_combo, 1)
        lv.addLayout(prow)
        many = len(spec.axes) > 1
        self.panel_lab.setVisible(many)
        self.panel_combo.setVisible(many)
        self.tabs = QTabWidget()
        lv.addWidget(self.tabs, 1)
        self.tabs.addTab(self._page_tab(), "Page")
        self.tabs.addTab(self._text_tab(), "Text")
        self.tabs.addTab(self._axes_tab(), "Axes")
        self.tabs.addTab(self._legend_tab(), "Legend")
        brow = QHBoxLayout()
        self.b_reset = push("Reset to plot", icon_name="reset")
        self.b_reset.setToolTip("Restore the labels, legend texts, scales and limits taken from the plot")
        self.b_reset.clicked.connect(self._reset_all)
        brow.addWidget(self.b_reset)
        brow.addStretch()
        cancel = push("Cancel")
        cancel.clicked.connect(self.reject)
        self.b_save = push("Save…", "primary", icon_name="download")
        self.b_save.clicked.connect(self._accept)
        self.b_save.setDefault(True)
        brow.addWidget(cancel)
        brow.addWidget(self.b_save)
        lv.addLayout(brow)
        root.addWidget(left)

        # ---------------- preview ----------------
        right = QFrame()
        right.setObjectName("pane")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(14, 12, 14, 12)
        rv.setSpacing(6)
        hdr = QHBoxLayout()
        hdr.addWidget(label("Preview", "paneTitle"))
        hdr.addStretch()
        self.size_lab = label("", "hint")
        hdr.addWidget(self.size_lab)
        rv.addLayout(hdr)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.preview.setMinimumSize(300, 240)
        self.preview.setStyleSheet(f"background: {T.c('surface2')}; border-radius: 8px;")
        rv.addWidget(self.preview, 1)
        self.err = label("", "hint", wrap=True)
        self.err.setStyleSheet(f"color: {T.c('danger')};")
        self.err.setVisible(False)
        rv.addWidget(self.err)
        rv.addWidget(label("The preview is the exported figure scaled to fit; fonts and line widths are in true "
                           "proportion to the page size.", "hint", wrap=True))
        root.addWidget(right, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._update_preview)
        self.panel_combo.currentIndexChanged.connect(self._switch_panel)
        self._restore_settings()
        self._load_panel(0)
        self._schedule()

    # -- tabs ----------------------------------------------------------------------
    @staticmethod
    def _form_page():
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(12, 12, 12, 12)
        f.setVerticalSpacing(8)
        f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        return w, f

    @staticmethod
    def _scroll(w):
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setWidget(w)
        return sc

    def _page_tab(self):
        w, f = self._form_page()
        self.fmt = QComboBox()
        for t, _ in FORMATS:
            self.fmt.addItem(t)
        self.style_c = QComboBox()
        for t, _ in STYLES:
            self.style_c.addItem(t)
        self.preset = QComboBox()
        for t, _, _ in PRESETS:
            self.preset.addItem(t)
        self.w = QDoubleSpinBox()
        self.w.setRange(1.0, 30.0)
        self.w.setDecimals(2)
        self.w.setSingleStep(0.1)
        self.w.setSuffix(" in")
        self.h = QDoubleSpinBox()
        self.h.setRange(1.0, 30.0)
        self.h.setDecimals(2)
        self.h.setSingleStep(0.1)
        self.h.setSuffix(" in")
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 2400)
        self.dpi.setSingleStep(50)
        f.addRow("Format", self.fmt)
        f.addRow("Style", self.style_c)
        f.addRow("Size preset", self.preset)
        f.addRow("Width", self.w)
        f.addRow("Height", self.h)
        f.addRow("Resolution", self.dpi)
        f.addRow("", label("Resolution applies to PNG/TIFF and to images inside vector files.", "hint", wrap=True))
        self.preset.currentIndexChanged.connect(self._preset)
        for wd in (self.fmt, self.style_c):
            wd.currentIndexChanged.connect(self._schedule)
        for wd in (self.w, self.h):
            wd.valueChanged.connect(self._size_edited)
        self.dpi.valueChanged.connect(self._schedule)
        return self._scroll(w)

    def _text_tab(self):
        w, f = self._form_page()
        self.family = QComboBox()
        for t, _ in FAMILIES:
            self.family.addItem(t)
        self.font_size = QDoubleSpinBox()
        self.font_size.setRange(5, 36)
        self.font_size.setDecimals(1)
        self.font_size.setSingleStep(0.5)
        self.font_size.setSuffix(" pt")
        self.line_w = QDoubleSpinBox()
        self.line_w.setRange(0.3, 6.0)
        self.line_w.setDecimals(2)
        self.line_w.setSingleStep(0.25)
        self.line_w.setSuffix(" pt")
        self.ticks = QComboBox()
        self.ticks.addItems(["Inside", "Outside"])
        self.grid = QCheckBox("Show grid lines")
        self.titles = QCheckBox("Show panel titles")
        self.usetex = QCheckBox("Typeset all text with LaTeX")
        ok = latex_available()
        self.usetex.setEnabled(ok)
        self.usetex.setToolTip("Uses your LaTeX installation (latex + dvipng) for every label, exactly like a "
                               "LaTeX document." if ok else
                               "No LaTeX installation (latex + dvipng) was found. $…$ math in labels is still "
                               "typeset by Matplotlib's built-in math renderer.")
        f.addRow("Font", self.family)
        f.addRow("Font size", self.font_size)
        f.addRow("Line width", self.line_w)
        f.addRow("Tick marks", self.ticks)
        f.addRow("", self.grid)
        f.addRow("", self.titles)
        f.addRow("", self.usetex)
        hint = label(MATH_HINT + ("" if ok else " A LaTeX installation was not found, so the built-in math "
                                              "renderer is used."), "hint", wrap=True)
        hint.setTextFormat(Qt.RichText)
        f.addRow("", hint)
        self.family.currentIndexChanged.connect(self._schedule)
        self.ticks.currentIndexChanged.connect(self._schedule)
        for wd in (self.font_size, self.line_w):
            wd.valueChanged.connect(self._schedule)
        for wd in (self.grid, self.usetex):
            wd.toggled.connect(self._schedule)
        self.titles.toggled.connect(self._titles_toggled)
        return self._scroll(w)

    def _axes_tab(self):
        w, f = self._form_page()
        self.p_title = QLineEdit()
        self.p_x = QLineEdit()
        self.p_y = QLineEdit()
        self.p_y2 = QLineEdit()
        self.p_y2_lab = QLabel("Right y label")
        f.addRow("Panel title", self.p_title)
        f.addRow("x label", self.p_x)
        f.addRow("y label", self.p_y)
        f.addRow(self.p_y2_lab, self.p_y2)
        self.p_xscale, self.p_x0, self.p_x1, xrow = self._axis_row()
        self.p_yscale, self.p_y0, self.p_y1, yrow = self._axis_row()
        f.addRow(_section("x axis"))
        f.addRow("Scale", self.p_xscale)
        f.addRow("Range", xrow)
        f.addRow(_section("y axis"))
        f.addRow("Scale", self.p_yscale)
        f.addRow("Range", yrow)
        b = QPushButton("Reset this panel to the plot")
        b.setObjectName("ghost")
        b.clicked.connect(self._reset_panel)
        f.addRow("", b)
        hint = label("Ranges start at the limits shown on screen. Clear a field (or press Auto) to let the "
                     "axis fit the data.", "hint", wrap=True)
        f.addRow("", hint)
        for e in (self.p_title, self.p_x, self.p_y, self.p_y2, self.p_x0, self.p_x1, self.p_y0, self.p_y1):
            e.textChanged.connect(self._panel_edited)
        self.p_xscale.currentIndexChanged.connect(lambda _: self._scale_changed("x"))
        self.p_yscale.currentIndexChanged.connect(lambda _: self._scale_changed("y"))
        return self._scroll(w)

    def _axis_row(self):
        sc = QComboBox()
        for t, _ in SCALES:
            sc.addItem(t)
        a, b = _LimitEdit("auto"), _LimitEdit("auto")
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        h.addWidget(a, 1)
        h.addWidget(QLabel("to"))
        h.addWidget(b, 1)
        auto = QPushButton("Auto")
        auto.setToolTip("Fit this axis to the data")
        auto.clicked.connect(lambda: (a.clear(), b.clear()))
        h.addWidget(auto)
        return sc, a, b, row

    def _legend_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        self.lg_show = QCheckBox("Show the legend in this panel")
        v.addWidget(self.lg_show)
        f = QFormLayout()
        f.setVerticalSpacing(8)
        f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.lg_pos = QComboBox()
        for t, _, _ in LEGEND_POS:
            self.lg_pos.addItem(t)
        self.lg_ncol = QSpinBox()
        self.lg_ncol.setRange(1, 6)
        self.lg_scale = QSpinBox()
        self.lg_scale.setRange(50, 150)
        self.lg_scale.setSingleStep(5)
        self.lg_scale.setSuffix(" % of font size")
        self.lg_frame = QCheckBox("Draw a frame around the legend")
        f.addRow("Position", self.lg_pos)
        f.addRow("Columns", self.lg_ncol)
        f.addRow("Text size", self.lg_scale)
        f.addRow("", self.lg_frame)
        v.addLayout(f)
        v.addWidget(_section("Entries"))
        v.addWidget(label("One line per curve. Clear a line to leave that curve out of the legend.", "hint",
                          wrap=True))
        self.entries_box = QWidget()
        self.entries_lay = QFormLayout(self.entries_box)
        self.entries_lay.setContentsMargins(0, 0, 0, 0)
        self.entries_lay.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        v.addWidget(self.entries_box)
        v.addStretch()
        self.entry_edits: list[QLineEdit] = []
        self.lg_show.toggled.connect(self._panel_edited)
        self.lg_pos.currentIndexChanged.connect(self._schedule)
        self.lg_ncol.valueChanged.connect(self._schedule)
        self.lg_scale.valueChanged.connect(self._schedule)
        self.lg_frame.toggled.connect(self._schedule)
        return self._scroll(w)

    # -- panel state -------------------------------------------------------------------
    def _load_panel(self, i: int):
        self._loading = True
        self.cur = i
        p = self.panels[i]
        a = self.spec.axes[i]
        self.p_title.setText(p.title)
        self.p_title.setEnabled(self.titles.isChecked())
        self.p_x.setText(p.xlabel)
        self.p_y.setText(p.ylabel)
        has2 = p.ylabel2 is not None
        self.p_y2.setText(p.ylabel2 or "")
        self.p_y2.setVisible(has2)
        self.p_y2_lab.setVisible(has2)
        self.p_xscale.setCurrentIndex([s for _, s in SCALES].index(p.xscale))
        self.p_yscale.setCurrentIndex([s for _, s in SCALES].index(p.yscale))
        self.p_x0.setText(_fmt_lim(p.xlim[0]))
        self.p_x1.setText(_fmt_lim(p.xlim[1]))
        self.p_y0.setText(_fmt_lim(p.ylim[0]))
        self.p_y1.setText(_fmt_lim(p.ylim[1]))
        is_image = a.image is not None
        for wd in (self.p_yscale,):
            wd.setEnabled(not is_image)
        # legend entries
        while self.entries_lay.rowCount():
            self.entries_lay.removeRow(0)
        self.entry_edits = []
        ser = list(a.series) + (list(a.twin.series) if a.twin is not None else [])
        for k, (se, txt) in enumerate(zip(ser, p.labels)):
            e = QLineEdit(txt)
            e.setPlaceholderText("(not in legend)")
            e.textChanged.connect(self._panel_edited)
            sw = QLabel()
            sw.setFixedSize(22, 4)
            col = se.color or T.c("series")[k % len(T.c("series"))]
            sw.setStyleSheet(f"background: {col}; border-radius: 2px;")
            self.entries_lay.addRow(sw, e)
            self.entry_edits.append(e)
        if not ser:
            self.entries_lay.addRow(label("This panel has no curves (e.g. a colour map).", "hint"))
        self.lg_show.setChecked(p.legend)
        self.lg_show.setEnabled(bool(ser))
        self._loading = False

    def _store_panel(self):
        p = self.panels[self.cur]
        p.title = self.p_title.text()
        p.xlabel = self.p_x.text()
        p.ylabel = self.p_y.text()
        if p.ylabel2 is not None:
            p.ylabel2 = self.p_y2.text()
        p.xscale = SCALES[self.p_xscale.currentIndex()][1]
        p.yscale = SCALES[self.p_yscale.currentIndex()][1]
        p.xlim = (self.p_x0.value(), self.p_x1.value())
        p.ylim = (self.p_y0.value(), self.p_y1.value())
        p.legend = self.lg_show.isChecked()
        p.labels = [e.text() for e in self.entry_edits]

    def _switch_panel(self, i):
        if i < 0:
            return
        self._store_panel()
        self._load_panel(i)

    def _panel_edited(self, *_):
        if self._loading:
            return
        self._store_panel()
        self._schedule()

    def _scale_changed(self, axis: str):
        if self._loading:
            return
        log = (self.p_xscale if axis == "x" else self.p_yscale).currentIndex() == 1
        lo, hi = (self.p_x0, self.p_x1) if axis == "x" else (self.p_y0, self.p_y1)
        if log:                                   # a log axis cannot start at or below zero
            for e in (lo, hi):
                v = e.value()
                if v is not None and v <= 0:
                    e.clear()
        self._panel_edited()

    def _reset_panel(self):
        self.panels[self.cur] = copy.deepcopy(self.defaults[self.cur])
        self._load_panel(self.cur)
        self._schedule()

    def _reset_all(self):
        self.panels = copy.deepcopy(self.defaults)
        self._load_panel(self.cur)
        self._schedule()

    def _titles_toggled(self, on):
        self.p_title.setEnabled(on)
        self._schedule()

    def _preset(self, i):
        _, w, h = PRESETS[i]
        if w is not None:
            self.w.blockSignals(True)
            self.h.blockSignals(True)
            self.w.setValue(w)
            self.h.setValue(h)
            self.w.blockSignals(False)
            self.h.blockSignals(False)
            self._schedule()

    def _size_edited(self, *_):
        cur = (round(self.w.value(), 2), round(self.h.value(), 2))
        idx = next((k for k, (_, w, h) in enumerate(PRESETS) if w is not None and (w, h) == cur), len(PRESETS) - 1)
        self.preset.blockSignals(True)
        self.preset.setCurrentIndex(idx)
        self.preset.blockSignals(False)
        self._schedule()

    # -- options -------------------------------------------------------------------------
    def options(self) -> ExportOptions:
        self._store_panel()
        return ExportOptions(
            fmt=FORMATS[self.fmt.currentIndex()][1], style=STYLES[self.style_c.currentIndex()][1],
            w=self.w.value(), h=self.h.value(), dpi=self.dpi.value(), font_size=self.font_size.value(),
            family=FAMILIES[self.family.currentIndex()][1], usetex=self.usetex.isChecked() and self.usetex.isEnabled(),
            line_width=self.line_w.value(), ticks="in" if self.ticks.currentIndex() == 0 else "out",
            grid=self.grid.isChecked(), titles=self.titles.isChecked(), legend_pos=self.lg_pos.currentIndex(),
            legend_ncol=self.lg_ncol.value(), legend_frame=self.lg_frame.isChecked(),
            legend_scale=self.lg_scale.value() / 100.0, panels=copy.deepcopy(self.panels))

    def ext(self) -> str:
        return FORMATS[self.fmt.currentIndex()][1]

    def _restore_settings(self):
        s = self.settings

        def get(key, default, cast):
            try:
                v = s.value(f"export/{key}", default)
                return cast(v) if v is not None else default
            except (TypeError, ValueError):
                return default

        def as_bool(v):
            return v if isinstance(v, bool) else str(v).lower() == "true"

        for wd in (self.fmt, self.style_c, self.preset, self.family, self.ticks, self.lg_pos, self.w, self.h,
                   self.dpi, self.font_size, self.line_w, self.lg_ncol, self.lg_scale):
            wd.blockSignals(True)
        self.fmt.setCurrentIndex(get("fmt", 0, int))
        self.style_c.setCurrentIndex(get("style", 0, int))
        self.preset.setCurrentIndex(get("preset", 0, int))
        self.w.setValue(get("w", 3.4, float))
        self.h.setValue(get("h", 2.6, float))
        self.dpi.setValue(get("dpi", 600, int))
        self.family.setCurrentIndex(get("family", 0, int))
        self.font_size.setValue(get("font", 9.0, float))
        self.line_w.setValue(get("line_width", 1.5, float))
        self.ticks.setCurrentIndex(get("ticks", 0, int))
        self.grid.setChecked(get("grid", False, as_bool))
        self.titles.setChecked(get("titles", False, as_bool))
        self.usetex.setChecked(get("usetex", False, as_bool) and self.usetex.isEnabled())
        self.lg_pos.setCurrentIndex(get("legend_pos", 0, int))
        self.lg_ncol.setValue(get("legend_ncol", 1, int))
        self.lg_scale.setValue(get("legend_scale", 85, int))
        self.lg_frame.setChecked(get("legend_frame", False, as_bool))
        for wd in (self.fmt, self.style_c, self.preset, self.family, self.ticks, self.lg_pos, self.w, self.h,
                   self.dpi, self.font_size, self.line_w, self.lg_ncol, self.lg_scale):
            wd.blockSignals(False)

    def _save_settings(self):
        s = self.settings
        for key, val in (("fmt", self.fmt.currentIndex()), ("style", self.style_c.currentIndex()),
                         ("preset", self.preset.currentIndex()), ("w", self.w.value()), ("h", self.h.value()),
                         ("dpi", self.dpi.value()), ("family", self.family.currentIndex()),
                         ("font", self.font_size.value()), ("line_width", self.line_w.value()),
                         ("ticks", self.ticks.currentIndex()), ("grid", self.grid.isChecked()),
                         ("titles", self.titles.isChecked()), ("usetex", self.usetex.isChecked()),
                         ("legend_pos", self.lg_pos.currentIndex()), ("legend_ncol", self.lg_ncol.value()),
                         ("legend_scale", self.lg_scale.value()), ("legend_frame", self.lg_frame.isChecked())):
            s.setValue(f"export/{key}", val)

    def _accept(self):
        bad = [e for e in (self.p_x0, self.p_x1, self.p_y0, self.p_y1) if not e.ok()]
        if bad:
            self.tabs.setCurrentIndex(2)
            bad[0].setFocus()
            return
        self._save_settings()
        self.accept()

    # -- preview ---------------------------------------------------------------------------
    def _schedule(self, *_):
        if not self._loading:
            self._timer.start()

    def _update_preview(self):
        opts = self.options()
        dpr = self.devicePixelRatioF() or 1.0
        aw, ah = max(200, self.preview.width() - 24), max(160, self.preview.height() - 24)
        pdpi = max(30.0, min(aw / opts.w, ah / opts.h, 220.0))
        px = (round(opts.w * opts.dpi), round(opts.h * opts.dpi))
        fmt = FORMATS[self.fmt.currentIndex()][0].split(" ")[0]
        self.size_lab.setText(f"{opts.w:g} × {opts.h:g} in  ·  {fmt}" +
                              (f"  ·  {px[0]} × {px[1]} px" if opts.fmt in ("png", "tiff") else "  ·  vector"))
        try:
            data = preview_png(self.spec, opts, pdpi * dpr)
        except Exception as exc:  # invalid LaTeX, impossible limits …
            msg = (str(exc).strip().splitlines() or [type(exc).__name__])
            detail = msg[0] if "Parse" in type(exc).__name__ or "Expected" in msg[0] else msg[-1]
            hint = ("A label has invalid math between $…$ – check braces and commands. "
                    if ("Parse" in type(exc).__name__ or "Expected" in detail or "Unknown symbol" in detail) else
                    "Cannot draw the figure with these settings: ")
            self.err.setText(hint + detail)
            self.err.setVisible(True)
            self.b_save.setEnabled(False)
            return
        pm = QPixmap()
        pm.loadFromData(data, "PNG")
        pm.setDevicePixelRatio(dpr)
        self.preview.setPixmap(pm)
        self.err.setVisible(False)
        self.b_save.setEnabled(True)

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self._schedule()


def _section(text: str) -> QLabel:
    lab = QLabel(text.upper())
    lab.setObjectName("sectionTitle")
    lab.setContentsMargins(0, 8, 0, 0)
    return lab
