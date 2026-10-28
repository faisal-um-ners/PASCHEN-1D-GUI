"""Plot specifications built from run data (shared by the live monitor and the results browser)."""
from __future__ import annotations

import math

import numpy as np

from .. import schema as SC
from ..runs import RunData
from ..units import si_scale_for
from . import theme as T
from .plotting import AxesSpec, FigureSpec, ImageSpec, Mark, Series

VOLTAGES = ["V_app", "V_node", "V_source", "V_gap"]
CURRENTS = ["I_discharge", "I_transport_plasma", "I_transport_circuit", "I_emission_circuit",
            "I_emission_area", "I_displacement_gap"]
NUMERICS = ["cfl", "diffusion_cfl", "picard_iterations", "adaptive_substeps", "adaptive_cfl_est",
            "adaptive_diffusion_cfl_est", "adaptive_dt_sub"]

SPATIAL_GROUPS = [
    ("Densities", ["ne", "ni"], "density [m⁻³]", "log"),
    ("Potential", ["phi"], "φ", "linear"),
    ("Electric field", ["E"], "E", "linear"),
    ("Fluxes", ["Gamma_e", "Gamma_i"], "flux [m⁻²s⁻¹]", "linear"),
    ("Ionization", ["nu_i", "townsend_alpha"], "", "log"),
    ("Sources", ["S_ion", "S"], "source [m⁻³s⁻¹]", "linear"),
    ("Mobility", ["mu_e", "mu_i"], "μ [m²/(V·s)]", "log"),
    ("Diffusion", ["D_e", "D_i"], "D [m²/s]", "log"),
]

COLORS_Q = {
    "ne": "electron", "ni": "ion", "Gamma_e": "electron", "Gamma_i": "ion", "mu_e": "electron", "mu_i": "ion",
    "D_e": "electron", "D_i": "ion", "phi": "potential", "E": "field", "V_app": "app", "V_gap": "gap",
    "V_node": "potential", "I_discharge": "current",
}


def qcolor(q: str) -> str | None:
    role = COLORS_Q.get(q)
    return T.c("role")[role] if role else None


def time_scale(T_total: float) -> tuple[float, str]:
    sc, u = si_scale_for([T_total], "s")
    return sc, u


def x_scale(L: float, unit: str = "auto") -> tuple[float, str]:
    if unit == "auto":
        unit = "mm" if L < 0.05 else "cm"
    return {"m": 1.0, "cm": 1e-2, "mm": 1e-3, "µm": 1e-6}[unit], unit


def _unit_label(q):
    return SC.quantity_unit(q)


def history_spec(rd: RunData, quantities: list[str], t0=None, t1=None, max_points=6000,
                 title_suffix: str = "") -> FigureSpec:
    groups = [("Voltages", [q for q in quantities if q in VOLTAGES], "V"),
              ("Currents", [q for q in quantities if q in CURRENTS], "A")]
    others = [q for q in quantities if q not in VOLTAGES and q not in CURRENTS]
    for q in others:
        groups.append((SC.quantity_label(q), [q], SC.quantity_unit(q)))
    groups = [g for g in groups if g[1]]
    tsc, tu = time_scale(rd.T_total)
    axes = []
    for title, qs, unit in groups:
        data = []
        for q in qs:
            try:
                t, y = rd.temporal(q, max_points=max_points, t0=t0, t1=t1)
            except Exception:
                continue
            data.append((q, t, y))
        allv = np.concatenate([d[2] for d in data]) if data else np.array([])
        ysc, yu = si_scale_for(allv, unit) if unit else (1.0, "")
        ax = AxesSpec(title=title + title_suffix, xlabel=f"time [{tu}]",
                      ylabel=f"{title.lower() if len(qs) > 1 else SC.quantity_label(qs[0])}" + (f" [{yu}]" if yu else ""))
        for q, t, y in data:
            ax.series.append(Series(t / tsc, y / ysc, label=SC.quantity_label(q), color=qcolor(q),
                                    style="--" if q == "V_app" else "-"))
        ax.legend = len(data) > 1
        axes.append(ax)
    if not axes:
        axes = [AxesSpec(empty_text="Select one or more quantities")]
    n = len(axes)
    cols = 1 if n <= 2 else 2
    rows = int(math.ceil(n / cols))
    return FigureSpec(axes, rows=rows, cols=cols, sharex=False)


def profile_axes(rd: RunData, k, quantities: list[str], x_unit="auto", log_density=True,
                 overlay: list[int] | None = None) -> list[AxesSpec]:
    xsc, xu = x_scale(rd.L, x_unit)
    x = rd.x / xsc
    times = rd.snapshot_times()
    tsc, tu = time_scale(rd.T_total)
    axes = []
    avail = set(rd.available_spatial())
    for title, qs, ylab, scale in SPATIAL_GROUPS:
        qs = [q for q in qs if q in quantities and q in avail]
        if not qs:
            continue
        if title == "Densities":
            yscale = "log" if log_density else "linear"
        else:
            yscale = "linear" if title in ("Potential", "Electric field", "Fluxes", "Sources") else scale
        arrays = []
        ks = overlay if overlay else [k]
        for q in qs:
            for kk in ks:
                arrays.append((q, kk, rd.spatial(q, kk)))
        allv = np.concatenate([a[2] for a in arrays]) if arrays else np.array([])
        unit = SC.quantity_unit(qs[0])
        if title in ("Potential", "Electric field"):
            ysc, yu = si_scale_for(allv, unit)
        else:
            ysc, yu = 1.0, unit
        ylabel = (SC.quantity_label(qs[0]) if len(qs) == 1 else title.lower()) + (f" [{yu}]" if yu else "")
        ax = AxesSpec(title=title, xlabel=f"x [{xu}]", ylabel=ylabel, yscale=yscale)
        if overlay:
            import matplotlib
            cmap = matplotlib.colormaps["viridis"]
            for i, (q, kk, y) in enumerate(arrays):
                frac = (ks.index(kk) / max(len(ks) - 1, 1))
                col = None
                if cmap is not None:
                    r, g, b, _ = cmap(0.1 + 0.8 * frac)
                    col = "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))
                lab = f"{SC.quantity_label(q).split(' ')[-1]} t = {times[min(kk, len(times) - 1)] / tsc:.4g} {tu}"
                ax.series.append(Series(x, y / ysc, label=lab, color=col, style="-" if q in ("ne", "phi", "E",
                                                                                          "Gamma_e", "mu_e",
                                                                                          "D_e", "nu_i", "S")
                                        else "--"))
        else:
            for q, kk, y in arrays:
                ax.series.append(Series(x, y / ysc, label=SC.quantity_label(q), color=qcolor(q), width=2.0))
        ax.legend = len(ax.series) > 1
        axes.append(ax)
    return axes


def profiles_spec(rd: RunData, k, quantities, x_unit="auto", log_density=True, overlay=None) -> FigureSpec:
    axes = profile_axes(rd, k, quantities, x_unit, log_density, overlay)
    if not axes:
        axes = [AxesSpec(empty_text="No spatial data for the selected quantities")]
    n = len(axes)
    cols = 1 if n == 1 else 2
    rows = int(math.ceil(n / cols))
    return FigureSpec(axes, rows=rows, cols=cols)


def spacetime_spec(rd: RunData, q: str, log: bool = True, cmap: str = "inferno", x_unit="auto",
                   mark_t: float | None = None) -> FigureSpec:
    times, arr = rd.spatial_block(q)
    xsc, xu = x_scale(rd.L, x_unit)
    tsc, tu = time_scale(rd.T_total)
    unit = SC.quantity_unit(q)
    if arr.size == 0:
        return FigureSpec([AxesSpec(empty_text="No snapshots yet")])
    data = arr.copy()
    symlog = False
    if log and np.nanmin(data) < 0:
        symlog, log = True, False
    if q in ("phi", "E"):
        ysc, yu = si_scale_for(data, unit)
        data = data / ysc
        unit = yu
    im = ImageSpec(data=data, extent=(0, rd.L / xsc, float(times[0]) / tsc, float(times[-1]) / tsc if len(times) > 1
                                      else 1.0), log=log, symlog=symlog, cmap=cmap,
                   clabel=f"{SC.quantity_label(q)} [{unit}]")
    ax = AxesSpec(title=f"{SC.quantity_label(q)}  –  space–time map", xlabel=f"x [{xu}]", ylabel=f"time [{tu}]",
                  image=im, legend=False)
    if mark_t is not None:
        ax.marks.append(Mark("hline", y=mark_t / tsc, color="#ffffff", style="--"))
    return FigureSpec([ax])


def compare_spec(runs: list[tuple[str, RunData]], q: str, normalize: bool = False, kind: str = "temporal",
                 log: bool = False) -> FigureSpec:
    if not runs:
        return FigureSpec([AxesSpec(empty_text="Tick two or more runs to compare")])
    if kind == "temporal":
        Tmax = max(rd.T_total for _, rd in runs)
        tsc, tu = time_scale(Tmax)
        data = []
        for name, rd in runs:
            try:
                t, y = rd.temporal(q, max_points=5000)
                data.append((name, t, y))
            except Exception:
                pass
        allv = np.concatenate([d[2] for d in data]) if data else np.array([])
        unit = SC.quantity_unit(q)
        ysc, yu = si_scale_for(allv, unit) if (unit and not normalize) else (1.0, "" if normalize else unit)
        ax = AxesSpec(title=f"{SC.quantity_label(q)} – comparison", xlabel=f"time [{tu}]",
                      ylabel=SC.quantity_label(q) + (" (normalized)" if normalize else (f" [{yu}]" if yu else "")),
                      yscale="log" if log else "linear")
        for name, t, y in data:
            yy = y / (np.nanmax(np.abs(y)) or 1.0) if normalize else y / ysc
            ax.series.append(Series(t / tsc, yy, label=name))
        return FigureSpec([ax])
    # final profiles
    ax = AxesSpec(title=f"{SC.quantity_label(q)} – final profile", ylabel=SC.quantity_label(q),
                  yscale="log" if log else "linear")
    for name, rd in runs:
        if q not in rd.available_spatial():
            continue
        xsc, xu = x_scale(rd.L)
        ax.xlabel = f"x [{xu}]"
        y = rd.spatial(q, rd.nsave_valid - 1)
        if normalize:
            y = y / (np.nanmax(np.abs(y)) or 1.0)
        ax.series.append(Series(rd.x / xsc, y, label=name))
    return FigureSpec([ax])


def averaged_spec(rd: RunData, quantities, t0: float, t1: float, x_unit="auto", log_density=True) -> FigureSpec:
    times = rd.snapshot_times()
    sel = np.where((times >= t0) & (times <= t1))[0]
    if sel.size == 0:
        return FigureSpec([AxesSpec(empty_text="No snapshots inside the selected window")])
    xsc, xu = x_scale(rd.L, x_unit)
    tsc, tu = time_scale(rd.T_total)
    axes = []
    for title, qs, ylab, scale in SPATIAL_GROUPS:
        qs = [q for q in qs if q in quantities and q in rd.available_spatial()]
        if not qs:
            continue
        unit = SC.quantity_unit(qs[0])
        ax = AxesSpec(title=f"{title} – average over {t0 / tsc:.4g}–{t1 / tsc:.4g} {tu} ({sel.size} snapshots)",
                      xlabel=f"x [{xu}]", ylabel=(SC.quantity_label(qs[0]) if len(qs) == 1 else title.lower())
                      + (f" [{unit}]" if unit else ""),
                      yscale=("log" if (title == "Densities" and log_density) else "linear"))
        for q in qs:
            mm = rd._spatial_memmap(q)
            avg = np.asarray(mm[sel].mean(axis=0), dtype=float)
            ax.series.append(Series(rd.x / xsc, avg, label=SC.quantity_label(q), color=qcolor(q), width=2.0))
        ax.legend = len(qs) > 1
        axes.append(ax)
    n = len(axes)
    cols = 1 if n == 1 else 2
    return FigureSpec(axes, rows=int(math.ceil(n / cols)), cols=cols)
