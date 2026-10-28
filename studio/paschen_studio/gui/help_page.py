"""In-app documentation: quick start, studio guide, the solver's own tutorial/README, shortcuts, citation.

Markdown is rendered with Qt's own reader and then restyled (typography, code boxes, tables, images that fit
the column), with an "On this page" outline and find-in-page.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QGuiApplication, QImageReader, QKeySequence,
                           QShortcut, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument, QTextFormat,
                           QTextFrameFormat, QTextLength, QTextListFormat, QTextOption)
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QTextBrowser, QTextEdit, QVBoxLayout, QWidget)

from .. import ARXIV_URL, BIBTEX, PAPER_AUTHORS, PAPER_JOURNAL, PAPER_TITLE, PAPER_URL, REPO_URL
from .. import solver as S
from . import icons
from . import theme as T
from .builder import pane
from .widgets import icon_button, label, push

MAC = sys.platform == "darwin"
MONO = ["JetBrains Mono", "SF Mono", "Menlo", "Consolas", "DejaVu Sans Mono", "Courier New"]
MAX_TEXT_WIDTH = 880          # comfortable reading measure, px
_PROPORTIONAL = int(getattr(QTextBlockFormat.LineHeightTypes.ProportionalHeight, "value",
                            QTextBlockFormat.LineHeightTypes.ProportionalHeight))
_FIXED = int(getattr(QTextBlockFormat.LineHeightTypes.FixedHeight, "value", QTextBlockFormat.LineHeightTypes.FixedHeight))


def _keys(s: str) -> str:
    """Show shortcuts the way the platform does (⌘/⇧ on macOS)."""
    if not MAC:
        return s
    return s.replace("Ctrl+Shift+", "⇧⌘").replace("Ctrl+", "⌘").replace("Shift+", "⇧")


QUICKSTART = f"""
# Quick start

**PASCHEN-1D Studio** is a graphical front end for the PASCHEN-1D drift-diffusion–Poisson solver.
You never have to edit Python files: every setting of the solver is available in forms.

## 1 · Create a model
* **Home → New simulation – guided** walks you through gas, gap, voltage, circuit, emission and resolution.
* Or open one of the **validated cases** (nitrogen DBD, argon DC glow, argon/helium photoemission,
  deuterium DBD) and change only what you need.
* A *model* is a base case plus the settings you changed. It is saved as a small `*.p1d.json` file.

## 2 · Edit settings
* The **Model Builder** tree groups the solver's configuration blocks.
* Type values with units: `3.5 mm`, `16 pF`, `70 us`, `0.4 MOhm`, `inf`. Hover any field for the solver's
  own explanation; the ↺ button restores the case default.
* Settings that do not apply to your current choices are hidden (toggle **Inactive** to see them).
* **{_keys("Ctrl+K")}** finds any setting by name or meaning.
* The **Preview** shows the gap, the circuit diagram, V_app(t), a classical Paschen breakdown estimate and
  the transport coefficients – all computed with the solver's own functions.

## 3 · Check
The **Model check** runs PASCHEN-1D's `validate_simulation_config` and adds advice (run time, disk space,
stability, gas/closure consistency). Many problems have a one-click **fix** button.

## 4 · Run
* **F5** runs the model; **Test run** ({_keys("Shift+F5")}) runs 2 % of the time steps with the same dt.
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

_SHORTCUT_ROWS = [
    ("New simulation (guided)", "Ctrl+N"), ("Open model", "Ctrl+O"), ("Save model", "Ctrl+S"),
    ("Save model as", "Ctrl+Shift+S"), ("Undo / redo a setting change", "Ctrl+Z / Ctrl+Shift+Z"),
    ("Find a setting", "Ctrl+K"), ("Check model", "Ctrl+Shift+K"), ("Run", "F5"), ("Test run", "Shift+F5"),
    ("Home / Model / Simulate / Results / Help", "Ctrl+1 … Ctrl+5"), ("Find in this page", "Ctrl+F"),
    ("Quick start", "F1"), ("Toggle dark theme", "Ctrl+Shift+D"),
]
SHORTCUTS = ("# Keyboard shortcuts\n\n## Application\n\n| Action | Shortcut |\n|---|---|\n" +
             "".join(f"| {a} | {_keys(k)} |\n" for a, k in _SHORTCUT_ROWS) +
             "\n## Plots\n\n| Action | Mouse |\n|---|---|\n"
             "| Zoom | Mouse wheel / trackpad scroll |\n| Pan | Drag with the pan tool |\n"
             "| Reset the view | Double-click |\n| Export, copy, log scale | Right-click |\n")


# ---------------------------------------------------------------------------
# markdown clean-up
_IMG_TAG = re.compile(r"<img\b([^>]*?)/?>", re.I)
_ATTR = re.compile(r"""(\w+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_A_TAG = re.compile(r"""<a\b[^>]*?href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""", re.I | re.S)


def clean_markdown(md: str) -> str:
    """Qt's markdown reader silently drops everything after a raw HTML block (e.g. ``<img ...>``), so the few
    HTML constructs used in READMEs are rewritten as plain markdown first. Code blocks are left untouched."""
    def img(m):
        attrs = {a.group(1).lower(): (a.group(2) if a.group(2) is not None else a.group(3))
                 for a in _ATTR.finditer(m.group(1))}
        return f"![{attrs.get('alt', '')}]({attrs['src']})" if attrs.get("src") else ""

    out, fence = [], None
    for ln in md.splitlines():
        st = ln.lstrip()
        if fence is None and (st.startswith("```") or st.startswith("~~~")):
            fence = st[:3]
        elif fence is not None and st.startswith(fence):
            fence = None
        elif fence is None:
            ln = _IMG_TAG.sub(img, ln)
            ln = _A_TAG.sub(lambda m: f"[{m.group(2)}]({m.group(1)})", ln)
            ln = re.sub(r"</?(?:p|div|center|span|picture|source|sup|sub)\b[^>]*>", "", ln, flags=re.I)
            ln = re.sub(r"<br\s*/?>", " ", ln, flags=re.I)
            ln = re.sub(r"</?(?:b|strong)>", "**", ln, flags=re.I)
            ln = re.sub(r"</?(?:i|em)>", "*", ln, flags=re.I)
        out.append(ln)
    return "\n".join(out)


# ---------------------------------------------------------------------------
class DocBrowser(QTextBrowser):
    """Read-only markdown viewer with document typography, a centred reading column and fitted images."""

    pageLink = Signal(str)            # link to another .md document (relative path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("docBrowser")
        self.setFrameShape(QFrame.NoFrame)
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._on_link)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)   # long paths/URLs never widen the page
        self.base_pt = QApplication.font().pointSizeF()
        if self.base_pt <= 0:
            self.base_pt = 10.0
        self.base_dir: Path | None = None
        self.headings: list[tuple[int, str, int]] = []      # (level, text, block number)
        self._images: list[tuple[int, int, int]] = []       # (position, natural w, natural h)
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(40)
        self._fit_timer.timeout.connect(self._fit_images)

    # -- loading ------------------------------------------------------------------
    def show_markdown(self, md: str, base_dir: Path | None = None):
        self.base_dir = base_dir
        self.setSearchPaths([str(base_dir)] if base_dir else [])
        doc = self.document()
        doc.clear()
        body = QFont(QApplication.font())
        body.setPointSizeF(self.base_pt + 0.5)
        doc.setDefaultFont(body)
        doc.setDocumentMargin(6)
        doc.setMarkdown(clean_markdown(md), QTextDocument.MarkdownDialectGitHub)
        rf = doc.rootFrame().frameFormat()
        rf.setTopMargin(14)
        rf.setBottomMargin(40)
        doc.rootFrame().setFrameFormat(rf)
        self._restyle()
        self._update_margins()
        self._fit_images()
        self.verticalScrollBar().setValue(0)
        self.horizontalScrollBar().setValue(0)

    # -- styling ------------------------------------------------------------------
    def _restyle(self):
        t = T.current()
        doc = self.document()
        base = self.base_pt + 0.5
        c_text, c_muted, c_accent = QColor(t["text"]), QColor(t["text2"]), QColor(t["accent"])
        c_code_bg, c_border, c_head_bg = QColor(t["surface2"]), QColor(t["border"]), QColor(t["surface2"])
        sizes = {1: base + 10, 2: base + 5, 3: base + 2.5, 4: base + 1}
        cur = QTextCursor(doc)
        cur.beginEditBlock()
        code_runs, inline, tables = [], [], {}
        run_start = run_end = None
        b = doc.begin()
        while b.isValid():
            bf = b.blockFormat()
            lvl = bf.headingLevel()
            is_code = bf.nonBreakableLines() or bf.hasProperty(QTextFormat.BlockCodeFence)
            cur.setPosition(b.position())
            cur.setPosition(b.position() + max(0, b.length() - 1), QTextCursor.KeepAnchor)
            tab = cur.currentTable()
            if tab is not None:
                tables[id(tab)] = tab
            nbf = QTextBlockFormat()
            if lvl:
                # Qt sizes headings with a relative "FontSizeAdjustment" that overrides any point size,
                # so it is removed fragment by fragment before the real size is set.
                frags = []
                it = b.begin()
                while not it.atEnd():
                    fr = it.fragment()
                    frags.append((fr.position(), fr.length(), fr.charFormat()))
                    it += 1
                for pos, n, cf in frags:
                    cf.clearProperty(QTextFormat.FontSizeAdjustment)
                    cf.setFontPointSize(sizes.get(lvl, base + 1))
                    cf.setFontWeight(QFont.Bold if lvl > 1 else QFont.ExtraBold)
                    cf.setForeground(c_text)
                    hc = QTextCursor(doc)
                    hc.setPosition(pos)
                    hc.setPosition(pos + n, QTextCursor.KeepAnchor)
                    hc.setCharFormat(cf)
                nbf.setTopMargin({1: 2, 2: 26, 3: 18}.get(lvl, 12))
                nbf.setBottomMargin({1: 10, 2: 8}.get(lvl, 6))
                nbf.setLineHeight(115.0, _PROPORTIONAL)
            elif is_code:
                cf = QTextCharFormat()
                cf.setFontFamilies(MONO)
                cf.setFontFixedPitch(True)
                cf.setFontPointSize(base - 1.0)
                cf.setForeground(c_text)
                cur.mergeCharFormat(cf)
                nbf.setLineHeight(125.0, _PROPORTIONAL)
                if tab is None and b.textList() is None:
                    if run_start is None:
                        run_start = b.position()
                    run_end = b.position() + b.length() - 1
            elif bf.hasProperty(QTextFormat.BlockTrailingHorizontalRulerWidth):
                nbf.setTopMargin(4)
                nbf.setBottomMargin(4)
            else:
                nbf.setLineHeight(135.0 if tab is not None else 150.0, _PROPORTIONAL)
                tl = b.textList()
                if tl is not None:
                    nbf.setBottomMargin(3)
                    lf = tl.format()
                    if lf.style() in (QTextListFormat.ListDisc, QTextListFormat.ListCircle, QTextListFormat.ListSquare):
                        want = (QTextListFormat.ListDisc, QTextListFormat.ListCircle,
                                QTextListFormat.ListSquare)[min(2, max(0, lf.indent() - 1))]
                        if lf.style() != want:
                            lf.setStyle(want)
                            tl.setFormat(lf)
                elif tab is None:
                    nbf.setBottomMargin(10)
                if bf.intProperty(QTextFormat.BlockQuoteLevel) > 0:
                    q = QTextCharFormat()
                    q.setForeground(c_muted)
                    cur.mergeCharFormat(q)
                # inline code, links and images inside this block
                it = b.begin()
                while not it.atEnd():
                    fr = it.fragment()
                    cf0 = fr.charFormat()
                    if not cf0.isImageFormat() and (cf0.fontFixedPitch() or cf0.isAnchor()):
                        inline.append((fr.position(), fr.length(), cf0.fontFixedPitch(), cf0.isAnchor()))
                    it += 1
            if lvl or not is_code:
                if run_start is not None:
                    code_runs.append((run_start, run_end))
                    run_start = None
            cur.mergeBlockFormat(nbf)
            b = b.next()
        if run_start is not None:
            code_runs.append((run_start, run_end))

        for pos, n, mono, anchor in inline:
            cur.setPosition(pos)
            cur.setPosition(pos + n, QTextCursor.KeepAnchor)
            cf = QTextCharFormat()
            if mono:
                cf.setFontFamilies(MONO)
                cf.setFontPointSize(base - 1.0)
                cf.setBackground(c_code_bg)
            if anchor:
                cf.setForeground(c_accent)
                cf.setFontUnderline(False)
            cur.mergeCharFormat(cf)

        for tab in tables.values():
            tf = tab.format()
            tf.setBorder(1)
            tf.setBorderBrush(c_border)
            tf.setBorderStyle(QTextFrameFormat.BorderStyle_Solid)
            tf.setBorderCollapse(True)
            tf.setCellSpacing(0)
            tf.setCellPadding(7)
            tf.setTopMargin(6)
            tf.setBottomMargin(14)
            tf.setWidth(QTextLength(QTextLength.PercentageLength, 100))
            tab.setFormat(tf)
            for col in range(tab.columns()):
                cell = tab.cellAt(0, col)
                cfmt = cell.format()
                cfmt.setBackground(c_head_bg)
                cfmt.setFontWeight(QFont.DemiBold)
                cell.setFormat(cfmt)

        # code blocks: a padded, bordered box. The lines are taken out and re-inserted inside a frame that
        # starts right after the previous block, so no empty line appears above the box (working from the
        # end keeps earlier positions valid).
        for start, end in reversed(code_runs):
            cur.setPosition(start)
            cur.setPosition(end, QTextCursor.KeepAnchor)
            text = cur.selection().toPlainText()
            bfmt, cfmt = cur.blockFormat(), cur.charFormat()
            bfmt.setTopMargin(0)
            bfmt.setBottomMargin(0)
            bfmt.setNonBreakableLines(False)         # long lines wrap inside the box instead of widening the page
            cur.setPosition(max(0, start - 1))
            cur.setPosition(end, QTextCursor.KeepAnchor)
            cur.removeSelectedText()
            ff = QTextFrameFormat()
            ff.setBackground(c_code_bg)
            ff.setBorder(1)
            ff.setBorderBrush(c_border)
            ff.setBorderStyle(QTextFrameFormat.BorderStyle_Solid)
            ff.setPadding(10)
            ff.setTopMargin(2)
            ff.setBottomMargin(6)
            frame = cur.insertFrame(ff)
            for i, ln in enumerate(text.split("\n")):
                if i:
                    cur.insertBlock(bfmt, cfmt)
                else:
                    cur.setBlockFormat(bfmt)
                    cur.setCharFormat(cfmt)
                cur.insertText(ln, cfmt)
            after = QTextCursor(doc)
            after.setPosition(frame.lastPosition() + 1)
            if after.block().isValid() and not after.block().text():
                gap = QTextBlockFormat()                 # the empty block Qt keeps after a frame: make it a thin gap
                gap.setLineHeight(8.0, _FIXED)
                gap.setTopMargin(0)
                gap.setBottomMargin(0)
                after.setBlockFormat(gap)
        cur.endEditBlock()
        self._scan()

    def _scan(self):
        """Collect headings (for the outline) and images (for fitting) after all edits."""
        doc = self.document()
        self.headings, self._images = [], []
        cur = QTextCursor(doc)
        b = doc.begin()
        while b.isValid():
            lvl = b.blockFormat().headingLevel()
            if lvl and b.text().strip():
                self.headings.append((lvl, b.text().strip(), b.blockNumber()))
            it = b.begin()
            only_image = True
            has_image = False
            while not it.atEnd():
                fr = it.fragment()
                cf = fr.charFormat()
                if cf.isImageFormat():
                    has_image = True
                    size = self._natural_size(cf.toImageFormat().name())
                    if size:
                        self._images.append((fr.position(), *size))
                elif fr.text().strip():
                    only_image = False
                it += 1
            if has_image and only_image:
                cur.setPosition(b.position())
                bf = QTextBlockFormat()
                bf.setAlignment(Qt.AlignHCenter)
                bf.setLineHeight(100.0, _PROPORTIONAL)   # 150 % line height would add half an image of space
                bf.setTopMargin(6)
                bf.setBottomMargin(16)
                cur.mergeBlockFormat(bf)
            b = b.next()

    def _natural_size(self, name: str):
        if not name or "://" in name and not name.startswith("file:"):
            return None
        p = Path(QUrl(name).toLocalFile()) if name.startswith("file:") else Path(name)
        if not p.is_absolute() and self.base_dir is not None:
            p = self.base_dir / p
        if not p.exists():
            return None
        sz = QImageReader(str(p)).size()
        return (sz.width(), sz.height()) if sz.isValid() and sz.width() > 0 else None

    def _fit_images(self):
        if not self._images:
            return
        avail = max(160, self.viewport().width() - 2 * int(self.document().documentMargin()) - 8)
        cur = QTextCursor(self.document())
        cur.beginEditBlock()
        for pos, w0, h0 in self._images:
            w = min(w0, avail)
            cur.setPosition(pos)
            cur.setPosition(pos + 1, QTextCursor.KeepAnchor)
            fmt = cur.charFormat()
            if not fmt.isImageFormat():
                continue
            im = fmt.toImageFormat()
            if abs(im.width() - w) < 1:
                continue
            im.setWidth(w)
            im.setHeight(h0 * w / w0)
            cur.setCharFormat(im)
        cur.endEditBlock()

    # -- layout -------------------------------------------------------------------
    def _update_margins(self):
        side = max(24, (self.width() - MAX_TEXT_WIDTH) // 2)
        self.setViewportMargins(side, 0, max(8, side - self.verticalScrollBar().sizeHint().width()), 0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_margins()
        self._fit_timer.start()

    def scroll_to_block(self, number: int):
        b = self.document().findBlockByNumber(number)
        if b.isValid():
            y = self.document().documentLayout().blockBoundingRect(b).top()
            self.verticalScrollBar().setValue(int(max(0, y - 6)))

    # -- links --------------------------------------------------------------------
    def _on_link(self, url: QUrl):
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
            return
        if url.hasFragment() and not url.path():
            self.scrollToAnchor(url.fragment())
            return
        path = url.toLocalFile() if url.isLocalFile() else url.path()
        if path.lower().endswith(".md"):
            self.pageLink.emit(path)
            return
        p = Path(path)
        if not p.is_absolute() and self.base_dir is not None:
            p = self.base_dir / p
        if p.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))


# ---------------------------------------------------------------------------
class FindBar(QWidget):
    """Find-in-page field with match count, previous/next and highlighting of all matches."""

    def __init__(self, browser: DocBrowser, parent=None):
        super().__init__(parent)
        self.browser = browser
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(2)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Find in page")
        self.edit.setClearButtonEnabled(True)
        self.edit.addAction(icons.icon("search", T.c("text3"), 14), QLineEdit.LeadingPosition)
        self.edit.setFixedWidth(210)
        self.edit.setToolTip(f"Find in this page ({_keys('Ctrl+F')}) – Enter: next, Shift+Enter: previous")
        h.addWidget(self.edit)
        self.count = label("", "hint")
        self.count.setMinimumWidth(52)
        self.count.setAlignment(Qt.AlignCenter)
        h.addWidget(self.count)
        self.b_prev = icon_button("chevron_up", "Previous match", size=15)
        self.b_next = icon_button("chevron_down", "Next match", size=15)
        h.addWidget(self.b_prev)
        h.addWidget(self.b_next)
        self.matches: list[QTextCursor] = []
        self.index = -1
        self.edit.textChanged.connect(self._search)
        self.edit.returnPressed.connect(lambda: self.step(-1 if QGuiApplication.keyboardModifiers()
                                                          & Qt.ShiftModifier else 1))
        self.b_prev.clicked.connect(lambda: self.step(-1))
        self.b_next.clicked.connect(lambda: self.step(1))
        self._update_buttons()

    def reset(self):
        self.matches, self.index = [], -1
        if self.edit.text():
            self._search(self.edit.text())
        else:
            self._paint()

    def _search(self, text: str):
        self.matches, self.index = [], -1
        doc = self.browser.document()
        if text.strip():
            cur = QTextCursor(doc)
            while len(self.matches) < 1000:
                cur = doc.find(text, cur)
                if cur.isNull():
                    break
                self.matches.append(QTextCursor(cur))
            if self.matches:
                top = self.browser.cursorForPosition(self.browser.viewport().rect().topLeft()).position()
                self.index = next((i for i, c in enumerate(self.matches) if c.position() >= top), 0)
        self.edit.setProperty("invalid", bool(text.strip()) and not self.matches)
        self.edit.style().unpolish(self.edit)
        self.edit.style().polish(self.edit)
        self._paint()

    def step(self, d: int):
        if not self.matches:
            return
        self.index = (self.index + d) % len(self.matches)
        self._paint()

    def _paint(self):
        sels = []
        weak, strong = QColor(T.c("warning_soft")), QColor(T.c("warning"))
        for i, c in enumerate(self.matches):
            s = QTextEdit.ExtraSelection()
            s.cursor = c
            fmt = QTextCharFormat()
            fmt.setBackground(strong if i == self.index else weak)
            if i == self.index:
                fmt.setForeground(QColor("#ffffff"))
            s.format = fmt
            sels.append(s)
        self.browser.setExtraSelections(sels)
        if 0 <= self.index < len(self.matches):
            c = QTextCursor(self.matches[self.index])
            c.clearSelection()
            self.browser.setTextCursor(c)
            r = self.browser.cursorRect(c)
            vh = self.browser.viewport().height()
            if r.top() < 40 or r.bottom() > vh - 40:          # bring the match to the upper third
                sb = self.browser.verticalScrollBar()
                sb.setValue(sb.value() + r.top() - vh // 3)
        n = len(self.matches)
        self.count.setText(f"{self.index + 1} of {n}" if n else ("No matches" if self.edit.text().strip() else ""))
        active = bool(self.edit.text().strip())
        for w in (self.count, self.b_prev, self.b_next):
            w.setVisible(active)
        self._update_buttons()

    def _update_buttons(self):
        for b in (self.b_prev, self.b_next):
            b.setEnabled(len(self.matches) > 1)


# ---------------------------------------------------------------------------
class Outline(QFrame):
    """'On this page' list of section headings that follows the scroll position."""

    def __init__(self, browser: DocBrowser, parent=None):
        super().__init__(parent)
        self.browser = browser
        self.setObjectName("docOutline")
        self.setFixedWidth(230)
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 14, 10, 8)
        v.setSpacing(6)
        v.addWidget(label("ON THIS PAGE", "sectionTitle"))
        self.list = QListWidget()
        self.list.setObjectName("outlineList")
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.itemClicked.connect(self._go)
        v.addWidget(self.list, 1)
        self._blocks: list[int] = []
        browser.verticalScrollBar().valueChanged.connect(self._follow)

    def populate(self, headings):
        self.list.clear()
        self._blocks = []
        levels = sorted({lvl for lvl, _, _ in headings})
        if not levels:
            return 0
        top = levels[0]
        if [lvl for lvl, _, _ in headings].count(top) == 1 and len(levels) > 1:
            top = levels[1]                          # skip a single document title
        show = {top, top + 1} if sum(1 for lvl, _, _ in headings if lvl in (top, top + 1)) <= 40 else {top}
        for lvl, text, num in headings:
            if lvl not in show:
                continue
            it = QListWidgetItem(("      " if lvl > top else "") + text)
            it.setToolTip(text)
            if lvl > top:
                it.setForeground(QColor(T.c("text3")))
            self.list.addItem(it)
            self._blocks.append(num)
        self._follow()
        return len(self._blocks)

    def _go(self, it):
        row = self.list.row(it)
        if 0 <= row < len(self._blocks):
            self.browser.scroll_to_block(self._blocks[row])

    def _follow(self, *_):
        if not self._blocks:
            return
        y = self.browser.verticalScrollBar().value() + 24
        lay = self.browser.document().documentLayout()
        row = 0
        for i, num in enumerate(self._blocks):
            b = self.browser.document().findBlockByNumber(num)
            if b.isValid() and lay.blockBoundingRect(b).top() <= y:
                row = i
        self.list.blockSignals(True)
        self.list.setCurrentRow(row)
        self.list.blockSignals(False)


# ---------------------------------------------------------------------------
class HelpPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # ---- navigation ----
        left, lv, _, _ = pane("Help")
        self.nav = QListWidget()
        self.nav.setObjectName("helpNav")
        lv.addWidget(self.nav, 1)
        left.setFixedWidth(250)
        root.addWidget(left)

        # ---- document ----
        right = QFrame()
        right.setObjectName("pane")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        head = QWidget()
        head.setObjectName("paneHeader")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(18, 10, 12, 10)
        hl.setSpacing(8)
        self.doc_icon = QLabel()
        hl.addWidget(self.doc_icon)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        self.doc_title = label("", "paneTitle")
        self.doc_sub = label("", "hint")
        tv.addWidget(self.doc_title)
        tv.addWidget(self.doc_sub)
        hl.addLayout(tv)
        hl.addStretch(1)
        self.browser = DocBrowser()
        self.find = FindBar(self.browser)
        hl.addWidget(self.find)
        self.action_bar = QHBoxLayout()
        self.action_bar.setSpacing(6)
        hl.addLayout(self.action_bar)
        rv.addWidget(head)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.browser, 1)
        self.outline = Outline(self.browser)
        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background: {T.c('border')};")
        self._outline_sep = sep
        body.addWidget(sep)
        body.addWidget(self.outline)
        rv.addLayout(body, 1)
        root.addWidget(right, 1)
        self.browser.pageLink.connect(self._open_linked_page)

        # ---- pages ----
        studio_docs = S.studio_dir() / "docs"
        root_dir = S.solver_root()
        entries = [
            ("quickstart", "Quick start", "help", QUICKSTART, "Studio · get started in five steps"),
            ("guide", "Studio user guide", "book", studio_docs / "USER_GUIDE.md", "Studio documentation"),
            ("tutorial", "PASCHEN-1D tutorial", "book", root_dir / "TUTORIAL.md", "PASCHEN-1D documentation"),
            ("readme", "PASCHEN-1D README", "info", root_dir / "README.md", "PASCHEN-1D documentation"),
            ("ions", "Ion-transport validation", "flask", root_dir / "ION_TRANSPORT_VALIDATION.md",
             "PASCHEN-1D documentation"),
            ("shortcuts", "Keyboard shortcuts", "keyboard", SHORTCUTS, "Studio · keyboard and mouse"),
            ("cite", "Cite PASCHEN-1D", "quote", None, "Paper, BibTeX and source code"),
        ]
        self.pages: dict[str, tuple] = {}
        for key, title, ic, src, sub in entries:
            if isinstance(src, Path) and not src.exists():
                continue
            it = QListWidgetItem(icons.icon(ic, T.c("accent"), 16), title)
            it.setData(Qt.UserRole, key)
            self.nav.addItem(it)
            self.pages[key] = (title, ic, src, sub)
        self.nav.currentRowChanged.connect(self._show)
        sc = QShortcut(QKeySequence.Find, self)
        sc.activated.connect(lambda: (self.find.edit.setFocus(), self.find.edit.selectAll()))
        self.show_page("quickstart")

    # -- navigation ---------------------------------------------------------------
    def show_page(self, key: str):
        for i in range(self.nav.count()):
            if self.nav.item(i).data(Qt.UserRole) == key:
                self.nav.setCurrentRow(i)
                return

    def _open_linked_page(self, path: str):
        name = Path(path).name.lower()
        for key, (_, _, src, _) in self.pages.items():
            if isinstance(src, Path) and src.name.lower() == name:
                self.show_page(key)
                return
        p = Path(path)
        if not p.is_absolute() and self.browser.base_dir is not None:
            p = self.browser.base_dir / p
        if p.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_outline_visibility()

    def _update_outline_visibility(self):
        show = self.outline.list.count() >= 3 and self.width() >= 1080
        self.outline.setVisible(show)
        self._outline_sep.setVisible(show)

    def _clear_actions(self):
        while self.action_bar.count():
            w = self.action_bar.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def _show(self, row):
        it = self.nav.item(row)
        if it is None or not it.data(Qt.UserRole):
            return
        key = it.data(Qt.UserRole)
        title, ic, src, sub = self.pages[key]
        self._clear_actions()
        self.doc_icon.setPixmap(icons.pixmap(ic, T.c("accent"), 20))
        self.doc_title.setText(title)
        if key == "cite":
            md = (f"# Cite PASCHEN-1D\n\nIf you use PASCHEN-1D (and this studio) in published work, please cite\n\n"
                  f"> {PAPER_AUTHORS}, “{PAPER_TITLE}”, *{PAPER_JOURNAL}*.\n\n"
                  f"* Journal article: <{PAPER_URL}>\n* arXiv preprint: <{ARXIV_URL}>\n"
                  f"* Source code (solver and studio): <{REPO_URL}>\n\n"
                  f"## BibTeX\n\n```\n{BIBTEX}\n```\n")
            self.doc_sub.setText(sub)
            self.browser.show_markdown(md)
            b = push("Copy BibTeX", "primary", icon_name="copy")
            b.clicked.connect(lambda: QGuiApplication.clipboard().setText(BIBTEX))
            self.action_bar.addWidget(b)
            b2 = push("Open paper", icon_name="external")
            b2.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PAPER_URL)))
            self.action_bar.addWidget(b2)
        elif isinstance(src, Path):
            self.doc_sub.setText(f"{sub}  ·  {src.name}")
            self.browser.show_markdown(src.read_text(encoding="utf-8", errors="replace"), src.parent)
            b = icon_button("external", f"Open {src.name} in your default application\n{src}", size=16,
                            text="Open file")
            b.clicked.connect(lambda _=None, p=src: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))))
            self.action_bar.addWidget(b)
        else:
            self.doc_sub.setText(sub)
            self.browser.show_markdown(src)
        self.outline.populate(self.browser.headings)
        self._update_outline_visibility()
        self.find.reset()
