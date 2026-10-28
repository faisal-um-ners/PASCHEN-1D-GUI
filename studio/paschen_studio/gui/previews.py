"""Live previews of the model: gap schematic, circuit diagram and physics plots."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from .. import advisor as A
from .. import schema as SC
from .. import solver as S
from ..units import format_quantity, si_scale_for
from . import theme as T
from .plotting import AxesSpec, FigureSpec, Mark, PlotCanvas, Series


def _q(v, unit, digits=3):
    return format_quantity(v, unit, digits=digits)


# ---------------------------------------------------------------------------
# Gap schematic
# ---------------------------------------------------------------------------
class DeviceSchematic(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.v: dict = {}
        self.setMinimumHeight(260)

    def set_values(self, v: dict):
        self.v = dict(v)
        self.update()

    def paintEvent(self, e):
        if not self.v:
            return
        v = self.v
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        text = QColor(T.c("text"))
        text2 = QColor(T.c("text2"))
        e_col = QColor(T.c("role")["electron"])
        i_col = QColor(T.c("role")["ion"])
        f = QFont(self.font())
        fs = f.pointSizeF()

        top, bot = 58, H - 64
        left_x, right_x = max(70, W * 0.16), min(W - 70, W * 0.84)
        ew = 20
        # gas region
        gas = QRectF(left_x + ew, top, right_x - left_x - 2 * ew, bot - top)
        grad = QLinearGradient(gas.topLeft(), gas.topRight())
        base = QColor(T.c("accent"))
        g1 = QColor(base)
        g1.setAlpha(18)
        g2 = QColor("#a855f7")
        g2.setAlpha(34)
        grad.setColorAt(0.0, g1)
        grad.setColorAt(0.8, g2)
        grad.setColorAt(1.0, g1)
        p.fillRect(gas, grad)
        # gas particles
        rng = np.random.default_rng(3)
        p.setPen(Qt.NoPen)
        dot = QColor(T.c("text3"))
        dot.setAlpha(90)
        p.setBrush(dot)
        for _ in range(70):
            x = gas.left() + 6 + rng.random() * (gas.width() - 12)
            y = gas.top() + 6 + rng.random() * (gas.height() - 12)
            p.drawEllipse(QPointF(x, y), 1.6, 1.6)
        # dielectric layers
        l = float(v.get("geometry.l") or 0.0)
        L = float(v.get("geometry.L") or 1e-3)
        dw = max(8.0, min(40.0, (l / (L + 2 * l)) * (right_x - left_x))) if l > 0 else 0.0
        # free gas between the dielectric layers: all captions stay inside it
        inner = QRectF(gas.left() + dw + 4, gas.top(), gas.width() - 2 * dw - 8, gas.height())
        if l > 0:
            diel = QColor("#38bdf8")
            diel.setAlpha(70)
            for r in (QRectF(left_x + ew, top, dw, bot - top), QRectF(right_x - ew - dw, top, dw, bot - top)):
                p.fillRect(r, diel)
                p.setPen(QPen(QColor("#0ea5e9"), 1, Qt.DashLine))
                p.drawRect(r)
            p.setPen(text2)
            p.drawText(QRectF(left_x, bot + 12, right_x - left_x, 16), Qt.AlignCenter,
                       f"dielectric layers {_q(l, 'm')} each, εr = {float(v.get('geometry.eps_r', 1)):.3g}")
        # electrodes
        for x, name in ((left_x, "anode"), (right_x - ew, "cathode")):
            r = QRectF(x, top - 10, ew, bot - top + 20)
            mg = QLinearGradient(r.topLeft(), r.topRight())
            mg.setColorAt(0, QColor("#94a3b8"))
            mg.setColorAt(0.5, QColor("#e2e8f0"))
            mg.setColorAt(1, QColor("#64748b"))
            p.setPen(QPen(QColor("#475569"), 1))
            p.setBrush(mg)
            p.drawRoundedRect(r, 3, 3)
        # labels
        f.setBold(True)
        f.setPointSizeF(fs)
        p.setFont(f)
        p.setPen(text)
        p.drawText(QRectF(left_x - 60, 8, 140, 18), Qt.AlignCenter, "Anode  x = 0")
        p.drawText(QRectF(right_x - 80, 8, 140, 18), Qt.AlignCenter, "Cathode  x = L")
        f.setBold(False)
        f.setPointSizeF(fs - 1)
        p.setFont(f)
        p.setPen(text2)
        p.drawText(QRectF(left_x - 60, 26, 140, 16), Qt.AlignCenter, "φ = V_gap(t)")
        p.drawText(QRectF(right_x - 80, 26, 140, 16), Qt.AlignCenter, "φ = 0 (ground)")
        # dimension arrow
        y = bot + 34 if l > 0 else bot + 26
        p.setPen(QPen(text2, 1.2))
        p.drawLine(QPointF(left_x + ew, y), QPointF(right_x - ew, y))
        for xa, d in ((left_x + ew, 1), (right_x - ew, -1)):
            p.drawLine(QPointF(xa, y), QPointF(xa + 7 * d, y - 4))
            p.drawLine(QPointF(xa, y), QPointF(xa + 7 * d, y + 4))
        f.setBold(True)
        p.setFont(f)
        p.setPen(text)
        p.drawText(QRectF(left_x, y + 4, right_x - left_x, 18), Qt.AlignCenter,
                   f"L = {_q(L, 'm')}     A = {float(v.get('geometry.A', 0)) * 1e4:.3g} cm²")
        # gas caption
        f.setBold(False)
        p.setFont(f)
        pT = float(v.get("plasma_state.p_Torr") or 0)
        gas_name = str(v.get("plasma_state.gas", ""))
        p.setPen(text)
        parts = [gas_name.capitalize(), f"{pT:.4g} Torr", f"pd = {pT * L * 100:.3g} Torr·cm"]
        cap = "  ·  ".join(x.replace(" ", "\u00a0") for x in parts)     # wrap only between the items
        cap_r = p.boundingRect(QRectF(inner.left(), inner.top() + 6, inner.width(), 200),
                               Qt.AlignHCenter | Qt.TextWordWrap, cap)
        p.drawText(QRectF(inner.left(), inner.top() + 6, inner.width(), cap_r.height()),
                   Qt.AlignHCenter | Qt.TextWordWrap, cap)
        n0 = float(v.get("plasma_state.n0") or 0)
        p.setPen(text2)
        p.drawText(QRectF(inner.left(), inner.top() + 8 + cap_r.height(), inner.width(), 16), Qt.AlignCenter,
                   f"n₀ = {n0:.3g} m⁻³" if n0 > 0 else "no initial plasma (n₀ = 0)")
        # transport arrows
        cy = gas.center().y()
        self._arrow(p, QPointF(inner.right() - 20, cy - 18), QPointF(inner.left() + 20, cy - 18), e_col,
                    "electrons → anode")
        self._arrow(p, QPointF(inner.left() + 20, cy + 18), QPointF(inner.right() - 20, cy + 18), i_col,
                    "ions → cathode")
        # emission
        mechs_c = SC.emission_mechanisms(v, "cathode")
        mechs_a = SC.emission_mechanisms(v, "anode")
        gamma = float(v.get("emission.gamma") or 0)
        lines = []
        if gamma > 0:
            lines.append(f"γ = {gamma:g} (ion-induced)")
        names = {"constant_J": "constant J", "fn": "Fowler–Nordheim", "mg": "Murphy–Good",
                 "rd": "thermionic", "quantum_pulse": "photoemission"}
        lines += [names[m] for m in mechs_c]
        yb = bot - 18 - 16 * len(lines)
        for i, t in enumerate(lines):
            yy = yb + 16 * i
            xr = inner.right() + 2                    # emitting surface (dielectric face or bare cathode)
            p.setPen(QPen(e_col, 1.6))
            p.drawLine(QPointF(xr, yy + 8), QPointF(xr - 18, yy + 8))
            p.drawLine(QPointF(xr - 18, yy + 8), QPointF(xr - 12, yy + 4))
            p.drawLine(QPointF(xr - 18, yy + 8), QPointF(xr - 12, yy + 12))
            p.setPen(text2)
            p.drawText(QRectF(inner.left(), yy, inner.width() - 24, 16), Qt.AlignRight | Qt.AlignVCenter, t)
        if mechs_a:
            for i, m in enumerate(mechs_a):
                yy = bot - 34 - 16 * i
                p.setPen(text2)
                p.drawText(QRectF(inner.left() + 6, yy, inner.width() - 12, 16), Qt.AlignLeft | Qt.AlignVCenter,
                           f"anode: {names[m]}")
        if "quantum_pulse" in mechs_c:
            # laser beam entering the gap from above and hitting the cathode face
            beam = QColor("#a855f7")
            sx, sy = gas.right() - 80, top - 30
            ex, ey = right_x - ew - 1, top + 42
            p.setPen(QPen(QColor(168, 85, 247, 70), 7))
            p.drawLine(QPointF(sx, sy), QPointF(ex, ey))
            p.setPen(QPen(beam, 2.4))
            p.drawLine(QPointF(sx, sy), QPointF(ex, ey))
            f.setPointSizeF(fs - 1.5)
            f.setBold(True)
            p.setFont(f)
            p.setPen(beam)
            lam = v.get("emission.shared_emission_lambda_m") if v.get("emission.electrode_material_mode") == "shared" \
                else v.get("emission.cathode_emission_lambda_m")
            p.drawText(QRectF(sx - 150, sy - 10, 144, 16), Qt.AlignRight | Qt.AlignVCenter,
                       f"laser {_q(lam or 0, 'm')}")
            f.setBold(False)
        if v.get("boundary.enable_volume_sources") and v.get("boundary.enable_ionization_source"):
            p.setPen(text2)
            f.setPointSizeF(fs - 1)
            p.setFont(f)
            p.drawText(QRectF(inner.left(), cy + 30, inner.width(), 34), Qt.AlignHCenter | Qt.TextWordWrap,
                       "impact ionization" + (" + recombination" if v.get("boundary.enable_recombination_sink") else ""))
        p.end()

    def _arrow(self, p, a: QPointF, b: QPointF, col: QColor, text: str):
        p.setPen(QPen(col, 2))
        p.drawLine(a, b)
        d = 1 if b.x() > a.x() else -1
        p.drawLine(b, QPointF(b.x() - 8 * d, b.y() - 4))
        p.drawLine(b, QPointF(b.x() - 8 * d, b.y() + 4))
        p.setPen(col)
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() - 1)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(min(a.x(), b.x()), a.y() - 18, abs(b.x() - a.x()), 16), Qt.AlignCenter, text)


# ---------------------------------------------------------------------------
# Circuit diagram
# ---------------------------------------------------------------------------
class CircuitDiagram(QWidget):
    """Schematic of the selected external-circuit topology with element values."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.v: dict = {}
        self.setMinimumHeight(250)

    def set_values(self, v: dict):
        self.v = dict(v)
        self.update()

    # element state: active / short / open (MNA neutral values)
    def _state(self, name: str) -> str:
        v = self.v
        val = float(v.get(f"circuit.{name}") or 0.0)
        if v.get("circuit.circuit_time_scheme") != "mna":
            return "active"
        if name in ("R0", "L_s", "R_m") and val == 0:
            return "short"
        if name == "C_s" and math.isinf(val):
            return "short"
        if name in ("C_p", "C_ext") and val == 0:
            return "open"
        if name == "L_p" and math.isinf(val):
            return "open"
        return "active"

    def paintEvent(self, e):
        if not self.v:
            return
        v = self.v
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        topo = v.get("circuit.circuit_type", "")
        els = SC.TOPOLOGY_ELEMENTS.get(topo, [])
        wire = QColor(T.c("text"))
        self._text = QColor(T.c("text"))
        self._text2 = QColor(T.c("text2"))
        self._accent = QColor(T.c("accent"))
        self._ghost = QColor(T.c("text3"))
        top, gnd = 96, H - 46
        series = [n for n in ("R0", "C_s", "L_s") if n in els]
        shunts = [n for n in ("C_p", "L_p") if n in els]
        has_rm = "R_m" in els
        has_cext = "C_ext" in els
        dielectric = float(v.get("geometry.l") or 0) > 0
        # x positions: fit everything (plus the plasma label) into the widget width
        units = (len(series) + 0.35 + len(shunts) + 0.5 * max(0, len(shunts) - 1) + (1.0 if has_rm else 0.0)
                 + (0.8 if has_cext else 0.0) + 0.8)
        x0 = 118                         # room for the source label on its left
        step = max(36.0, min(130.0, (W - x0 - 140) / max(units, 1.0)))
        xs = x0
        p.setPen(QPen(wire, 1.6))
        # source
        self._source(p, xs, top, gnd)
        x = xs
        nodes = []
        for name in series:
            x2 = x + step
            self._series(p, name, x, x2, top)
            x = x2
        node_x = x + (step * 0.35 if shunts or has_rm else step * 0.35)
        p.setPen(QPen(wire, 1.6))
        p.drawLine(QPointF(x, top), QPointF(node_x, top))
        x = node_x
        if topo != "dielectric_plasma":
            nodes.append((x, "V_node" if (has_rm or shunts) else "V_gap"))
        for name in shunts:
            p.setPen(QPen(wire, 1.6))
            p.drawLine(QPointF(x, top), QPointF(x + step * 0.5, top))
            x += step * 0.5
            # the first shunt is labelled on its left; a second one (Lp next to Cp) on its right, with extra
            # room after it, so no label touches a neighbouring element
            right = name != shunts[0]
            self._shunt(p, name, x, top, gnd, label_left=not right)
            last_shunt_x = x
            gap = step * (1.0 if right else 0.5)
            p.setPen(QPen(wire, 1.6))
            p.drawLine(QPointF(x, top), QPointF(x + gap, top))
            x += gap
        if has_rm:
            x2 = x + step
            self._series(p, "R_m", x, x2, top)
            x = x2
            nodes.append((x, "V_gap"))
        if has_cext:
            nx = x + step * 0.8
            if len(shunts) > 1:                  # keep the Lp label (right of Lp) clear of the Cext label
                nx = max(nx, last_shunt_x + 128)
            p.setPen(QPen(wire, 1.6))
            p.drawLine(QPointF(x, top), QPointF(nx, top))
            x = nx
            self._shunt(p, "C_ext", x, top, gnd, label_left=True)
        p.setPen(QPen(wire, 1.6))
        p.drawLine(QPointF(x, top), QPointF(x + step * 0.8, top))
        x += step * 0.8
        self._plasma(p, x, top, gnd, dielectric)
        # ground rail
        p.setPen(QPen(wire, 1.6))
        p.drawLine(QPointF(xs, gnd), QPointF(x, gnd))
        self._ground(p, (xs + x) / 2, gnd)
        for nx, nm in nodes:
            p.setBrush(wire)
            p.drawEllipse(QPointF(nx, top), 3.2, 3.2)
            self._label(p, nx, top - 24, nm, self._accent, bold=True)
        # title
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.setPen(self._text)
        p.drawText(QRectF(12, 6, W - 24, 18), Qt.AlignLeft, SC.choice_label(topo))
        f.setBold(False)
        f.setPointSizeF(f.pointSizeF() - 1)
        p.setFont(f)
        p.setPen(self._text2)
        p.drawText(QRectF(12, 24, W - 24, 16), Qt.AlignLeft,
                   f"time integration: {SC.choice_label(v.get('circuit.circuit_time_scheme', ''))}")
        p.end()

    def _label(self, p, x, y, text, col=None, bold=False, sub=""):
        f = QFont(self.font())
        f.setBold(bold)
        f.setPointSizeF(f.pointSizeF() - (0 if bold else 0.5))
        p.setFont(f)
        p.setPen(col or self._text)
        p.drawText(QRectF(x - 60, y, 120, 16), Qt.AlignCenter, text)
        if sub:
            f.setBold(False)
            f.setPointSizeF(f.pointSizeF() - 0.5)
            p.setFont(f)
            p.setPen(self._text2)
            p.drawText(QRectF(x - 60, y + 15, 120, 16), Qt.AlignCenter, sub)

    def _value(self, name):
        unit = {"R0": "Ω", "R_m": "Ω", "C_s": "F", "C_p": "F", "C_ext": "F", "L_s": "H", "L_p": "H"}[name]
        return _q(float(self.v.get(f"circuit.{name}") or 0.0), unit)

    def _series(self, p, name, x1, x2, y):
        st = self._state(name)
        col = self._ghost if st != "active" else QColor(T.c("text"))
        mid = (x1 + x2) / 2
        p.setPen(QPen(QColor(T.c("text")), 1.6))
        if st == "short":
            p.drawLine(QPointF(x1, y), QPointF(x2, y))
            self._label(p, mid, y + 8, name.replace("_", ""), self._ghost, sub="short")
            return
        p.drawLine(QPointF(x1, y), QPointF(mid - 18, y))
        p.drawLine(QPointF(mid + 18, y), QPointF(x2, y))
        p.setPen(QPen(col, 1.8))
        self._body(p, name[0], QPointF(mid - 18, y), QPointF(mid + 18, y))
        self._label(p, mid, y + 12, name.replace("_", ""), self._text, True, self._value(name))

    def _shunt(self, p, name, x, y1, y2, label_left: bool = False, label_dy: float = 0.0):
        st = self._state(name)
        mid = (y1 + y2) / 2
        if st == "open":
            p.setPen(QPen(self._ghost, 1.2, Qt.DashLine))
            p.drawLine(QPointF(x, y1), QPointF(x, y1 + 18))
            p.drawLine(QPointF(x, y2 - 18), QPointF(x, y2))
            self._label(p, x, mid - 10, name.replace("_", ""), self._ghost, sub="open")
            return
        p.setPen(QPen(QColor(T.c("text")), 1.6))
        p.drawLine(QPointF(x, y1), QPointF(x, mid - 18))
        p.drawLine(QPointF(x, mid + 18), QPointF(x, y2))
        p.setBrush(QColor(T.c("text")))
        p.drawEllipse(QPointF(x, y1), 3.2, 3.2)
        p.drawEllipse(QPointF(x, y2), 3.2, 3.2)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(T.c("text")), 1.8))
        self._body(p, name[0], QPointF(x, mid - 18), QPointF(x, mid + 18))
        # label hugs its own element (right-aligned on the left side, left-aligned on the right side)
        y = mid - 14 + label_dy
        box = QRectF(x - 16 - 90, y, 90, 16) if label_left else QRectF(x + 16, y, 90, 16)
        align = (Qt.AlignRight if label_left else Qt.AlignLeft) | Qt.AlignVCenter
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.setPen(self._text)
        p.drawText(box, align, name.replace("_", ""))
        f.setBold(False)
        f.setPointSizeF(f.pointSizeF() - 1.0)
        p.setFont(f)
        p.setPen(self._text2)
        p.drawText(QRectF(box.left(), y + 15, box.width(), 16), align, self._value(name))

    def _body(self, p, kind, a: QPointF, b: QPointF):
        """Draw element body between a and b (horizontal or vertical)."""
        horiz = abs(b.x() - a.x()) > abs(b.y() - a.y())
        length = (b.x() - a.x()) if horiz else (b.y() - a.y())

        def pt(t, off):
            if horiz:
                return QPointF(a.x() + t * length, a.y() + off)
            return QPointF(a.x() + off, a.y() + t * length)

        p.setBrush(Qt.NoBrush)
        if kind == "R":
            path = QPainterPath(pt(0, 0))
            n = 6
            for i in range(n):
                path.lineTo(pt((i + 0.5) / n, 7 if i % 2 == 0 else -7))
            path.lineTo(pt(1, 0))
            p.drawPath(path)
        elif kind == "C":
            p.drawLine(pt(0, 0), pt(0.42, 0))
            p.drawLine(pt(0.58, 0), pt(1, 0))
            p.setPen(QPen(p.pen().color(), 2.4))
            p.drawLine(pt(0.42, -11), pt(0.42, 11))
            p.drawLine(pt(0.58, -11), pt(0.58, 11))
        elif kind == "L":
            path = QPainterPath(pt(0, 0))
            n = 4
            for i in range(n):
                t0, t1 = i / n, (i + 1) / n
                path.cubicTo(pt(t0, -11), pt(t1, -11), pt(t1, 0))
            p.drawPath(path)

    def _source(self, p, x, y1, y2):
        mid = (y1 + y2) / 2
        p.setPen(QPen(QColor(T.c("text")), 1.6))
        p.drawLine(QPointF(x, y1), QPointF(x, mid - 18))
        p.drawLine(QPointF(x, mid + 18), QPointF(x, y2))
        p.setBrush(QColor(T.c("surface")))
        p.drawEllipse(QPointF(x, mid), 18, 18)
        path = QPainterPath(QPointF(x - 10, mid))
        path.cubicTo(QPointF(x - 5, mid - 12), QPointF(x - 2, mid - 12), QPointF(x, mid))
        path.cubicTo(QPointF(x + 2, mid + 12), QPointF(x + 5, mid + 12), QPointF(x + 10, mid))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        wt = self.v.get("waveform.waveform_type", "")
        # label to the LEFT of the source, so it can never collide with a shunt element (Cp, Lp) on the right
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.setPen(self._text)
        box = QRectF(x - 24 - 110, mid - 4, 110, 16)
        p.drawText(box, Qt.AlignRight | Qt.AlignVCenter, "V_app(t)")
        f.setBold(False)
        f.setPointSizeF(f.pointSizeF() - 1.0)
        p.setFont(f)
        p.setPen(self._text2)
        p.drawText(QRectF(box.left(), box.top() + 15, box.width(), 16), Qt.AlignRight | Qt.AlignVCenter,
                   SC.choice_label(wt).split(" (")[0])

    def _plasma(self, p, x, y1, y2, dielectric):
        mid = (y1 + y2) / 2
        p.setPen(QPen(QColor(T.c("text")), 1.6))
        p.drawLine(QPointF(x, y1), QPointF(x, mid - 26))
        p.drawLine(QPointF(x, mid + 26), QPointF(x, y2))
        r = QRectF(x - 22, mid - 24, 44, 48)
        g = QRadialGradient(r.center(), 26)
        g.setColorAt(0, QColor(168, 85, 247, 150))
        g.setColorAt(1, QColor(99, 102, 241, 20))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(r, 6, 6)
        p.setPen(QPen(QColor("#475569"), 3))
        p.drawLine(QPointF(x - 18, mid - 26), QPointF(x + 18, mid - 26))
        p.drawLine(QPointF(x - 18, mid + 26), QPointF(x + 18, mid + 26))
        if dielectric:
            p.setPen(QPen(QColor("#0ea5e9"), 3))
            p.drawLine(QPointF(x - 18, mid - 21), QPointF(x + 18, mid - 21))
            p.drawLine(QPointF(x - 18, mid + 21), QPointF(x + 18, mid + 21))
        self._label(p, x + 64, mid - 14, "plasma gap", self._text, True,
                    "+ dielectric" if dielectric else f"C_gap = ε₀A/L")

    def _ground(self, p, x, y):
        p.setPen(QPen(QColor(T.c("text")), 1.6))
        p.drawLine(QPointF(x, y), QPointF(x, y + 10))
        for i, w in enumerate((14, 9, 4)):
            p.drawLine(QPointF(x - w, y + 10 + 4 * i), QPointF(x + w, y + 10 + 4 * i))


# ---------------------------------------------------------------------------
# Plot specs
# ---------------------------------------------------------------------------
def _scaled_time(t):
    sc, u = si_scale_for(t, "s")
    return np.asarray(t) / sc, u, sc


def waveform_spec(model) -> FigureSpec:
    res = A.waveform_preview(model)
    ax = AxesSpec(title="Applied voltage V_app(t)", ylabel="V_app [V]", legend=False,
                  empty_text="Waveform preview unavailable (check the waveform settings).")
    if res is not None:
        t, V = res
        ts, u, sc = _scaled_time(t)
        vs, vu = si_scale_for(V, "V")
        ax.ylabel = f"V_app [{vu}]"
        ax.xlabel = f"time [{u}]"
        ax.series.append(Series(ts, V / vs, color=T.c("role")["voltage"], fill=True, width=2.0))
        v = model.values()
        for elec in ("cathode", "anode"):
            mechs = SC.emission_mechanisms(v, elec)
            pre = "shared" if v.get("emission.electrode_material_mode") == "shared" else elec
            if "quantum_pulse" in mechs:
                t0 = float(v.get(f"emission.{pre}_laser_t0", 0))
                ax.marks.append(Mark("vline", x=t0 / sc, text=f"laser ({elec})", color="#a855f7"))
            if "constant_J" in mechs:
                ax.marks.append(Mark("vspan", x=float(v.get(f"emission.{pre}_emission_t_start", 0)) / sc,
                                     x2=float(v.get(f"emission.{pre}_emission_t_end", 0)) / sc, color="#a855f7"))
    return FigureSpec([ax])


def paschen_spec(model) -> tuple[FigureSpec, str]:
    pc = A.paschen_curve(model)
    ax = AxesSpec(title="Classical breakdown estimate (Townsend criterion)", xlabel="pd [Torr·cm]",
                  ylabel="breakdown voltage V_b [V]", xscale="log", yscale="log", legend=True,
                  empty_text="Not available for this ionization configuration.")
    note = ""
    if pc is not None:
        Vb = pc["Vb"]
        ok = np.isfinite(Vb)
        ax.series.append(Series(pc["pd"][ok], Vb[ok], label=f"γ = {pc['gamma']:g},  d = {_q(pc['d'], 'm')}",
                                color=T.c("accent"), width=2.0))
        v = model.values()
        Vop = abs(float(v.get("waveform.V_peak", 0)))
        if v.get("waveform.waveform_type") == "rf":
            Vop += abs(float(v.get("waveform.V_dc", 0)))
        col = T.c("success") if (math.isfinite(pc["Vb0"]) and Vop >= pc["Vb0"]) else T.c("warning")
        if Vop > 0:
            ax.marks.append(Mark("point", x=pc["pd0"], y=Vop, text=f"your V_peak = {_q(Vop, 'V')}", color=col))
        if math.isfinite(pc["Vb0"]):
            ax.marks.append(Mark("hline", y=pc["Vb0"], color=T.c("text3")))
            ax.marks.append(Mark("text", x=0.98, y=0.06, text=f"V_b ≈ {_q(pc['Vb0'], 'V')} at pd = {pc['pd0']:.3g} Torr·cm",
                                 color=T.c("text2")))
            ratio = Vop / pc["Vb0"] if pc["Vb0"] > 0 else float("inf")
            note = (f"Applied amplitude is {ratio:.2f} × the classical breakdown estimate "
                    f"({_q(pc['Vb0'], 'V')}). " +
                    ("Self-sustained breakdown is expected." if ratio >= 1 else
                     "Below the Townsend threshold: a discharge needs seed charge / emission or will not ignite."))
        else:
            note = "No Townsend breakdown at this pd and γ within the plotted voltage range."
        if "pd_min" in pc:
            note += f"  Paschen minimum ≈ {_q(pc['Vb_min'], 'V')} at pd ≈ {pc['pd_min']:.3g} Torr·cm."
    return FigureSpec([ax]), note


def transport_spec(model, narrow: bool = False) -> tuple[FigureSpec, str]:
    """α/N and μN versus E/N from the solver's own closures (equations or tables). ``narrow`` stacks the two
    panels vertically so they stay readable in a slim preview pane."""
    note = ""
    axes = []
    try:
        cfg = model.build_config()
        physics = S.import_solver_module("physics")
        est = A.estimate(model)
        N = float(physics.compute_background_neutral_density(cfg))
        EN = np.logspace(0, 3.5, 160)          # 1 .. 3000 Td
        E = (EN * 1e-21 * N).astype(np.float32)
        x = np.linspace(0, float(cfg.geometry.L), E.size)
        pT = float(cfg.plasma_state.p_Torr)
        pr = pT * 300.0 / max(float(cfg.plasma_state.T_i), 1.0)
        a1 = AxesSpec(title="Ionization", xlabel="E/N [Td]", ylabel="α/N [m²]", xscale="log", yscale="log")
        try:
            alpha = np.asarray(physics.build_townsend_alpha_profile(cfg, E, pT, pr, cfg.plasma_state.gas, N), float)
            a1.series.append(Series(EN, alpha / N, label="Townsend α/N", color=T.c("role")["current"]))
        except Exception as exc:
            a1.empty_text = f"α unavailable: {exc}"
        a2 = AxesSpec(title="Mobility", xlabel="E/N [Td]", ylabel="μ·N [1/(m·V·s)]", xscale="log", yscale="log")
        try:
            mu_e = np.abs(np.asarray(physics.build_electron_mobility_profile(cfg, x, E, N), float))
            a2.series.append(Series(EN, mu_e * N, label="electrons", color=T.c("role")["electron"]))
        except Exception as exc:
            note += f"Electron mobility unavailable: {exc}. "
        try:
            cache = physics.build_swarm_interpolation_cache(cfg)
            mu_i = np.abs(np.asarray(physics.build_ion_mobility_profile(cfg, x, E, N, cache), float))
            a2.series.append(Series(EN, mu_i * N, label=f"ions ({cfg.ion_transport.positive_ion})",
                                    color=T.c("role")["ion"]))
        except Exception as exc:
            note += f"Ion mobility unavailable: {exc}. "
        en0 = est["E_over_N_Td"]
        for a in (a1, a2):
            if math.isfinite(en0) and en0 > 0:
                a.marks.append(Mark("vline", x=en0, text=f"applied E/N ≈ {en0:.3g} Td", color=T.c("text3")))
        axes = [a1, a2]
        src_e = ("BOLSIG+ table" if "local_field_approximation.electron_swarm_data_path" in
                 SC.electron_tables_in_use(model.values()) else "physics.py equations")
        note = f"Curves come from the solver's own closures (electrons: {src_e}). " + note
    except Exception as exc:
        axes = [AxesSpec(empty_text=f"Transport preview unavailable: {exc}")]
    if narrow and len(axes) > 1:
        return FigureSpec(axes, rows=len(axes), cols=1), note
    return FigureSpec(axes, rows=1, cols=len(axes)), note


# ---------------------------------------------------------------------------
class GraphicsPanel(QWidget):
    """Tabbed preview area of the model builder."""

    TABS = ["Device", "Circuit", "Waveform", "Breakdown", "Transport"]
    GROUP_TAB = {
        "geometry": "Device", "plasma_state": "Breakdown", "boundary": "Device", "emission": "Device",
        "circuit": "Circuit", "waveform": "Waveform", "run": "Waveform", "plasma": "Transport",
        "local_field_approximation": "Transport", "ion_transport": "Transport", "townsend_coefficient": "Transport",
        "ionization_frequency_source": "Transport", "electron_swarm_data": "Transport", "recombination": "Device",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        v.addWidget(self.tabs)
        self.device = DeviceSchematic()
        self.circuit = CircuitDiagram()
        self.wave = PlotCanvas("", export_name="waveform")
        self.paschen = PlotCanvas("", export_name="paschen_estimate", log_toggle=False)
        self.paschen_note = QLabel()
        self.paschen_note.setObjectName("muted")
        self.paschen_note.setWordWrap(True)
        self.transport = PlotCanvas("", export_name="transport", log_toggle=False)
        self.transport_note = QLabel()
        self.transport_note.setObjectName("hint")
        self.transport_note.setWordWrap(True)
        self._pages = {}
        for name, w, extra in (("Device", self.device, None), ("Circuit", self.circuit, None),
                               ("Waveform", self.wave, None), ("Breakdown", self.paschen, self.paschen_note),
                               ("Transport", self.transport, self.transport_note)):
            page = QWidget()
            pl = QVBoxLayout(page)
            pl.setContentsMargins(6, 8, 6, 6)
            pl.addWidget(w, 1)
            if extra is not None:
                pl.addWidget(extra)
            self.tabs.addTab(page, name)
            self._pages[name] = page
        self._dirty = set(self.TABS)
        self.tabs.currentChanged.connect(lambda _: self._refresh_current())
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self._refresh_current)

    def set_model(self, model):
        self.model = model
        self.invalidate()

    def invalidate(self, paths=None):
        self._dirty = set(self.TABS)
        if self.model is not None:
            v = self.model.values()
            self.device.set_values(v)
            self.circuit.set_values(v)
        self._timer.start()

    def show_for_group(self, group: str):
        tab = self.GROUP_TAB.get(group)
        if tab:
            self.tabs.setCurrentWidget(self._pages[tab])

    def _refresh_current(self):
        if self.model is None:
            return
        name = self.tabs.tabText(self.tabs.currentIndex())
        if name not in self._dirty:
            return
        self._dirty.discard(name)
        try:
            if name == "Waveform":
                self.wave.set_spec(waveform_spec(self.model), keep_view=False)
            elif name == "Breakdown":
                spec, note = paschen_spec(self.model)
                self.paschen.set_spec(spec, keep_view=False)
                self.paschen_note.setText(note)
            elif name == "Transport":
                self._transport_narrow = self.width() < 560
                spec, note = transport_spec(self.model, narrow=self._transport_narrow)
                self.transport.set_spec(spec, keep_view=False)
                self.transport_note.setText(note)
        except Exception as exc:  # pragma: no cover - previews must never break the editor
            self.paschen_note.setText(f"Preview error: {exc}")

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        narrow = self.width() < 560
        if getattr(self, "_transport_narrow", None) not in (None, narrow):
            self._dirty.add("Transport")            # re-layout the transport panels (side by side ⇄ stacked)
            self._timer.start()

    def restyle(self):
        for c in (self.wave, self.paschen, self.transport):
            c.restyle()
        self.invalidate()
