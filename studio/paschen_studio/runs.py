"""Read PASCHEN-1D run folders - finished, stopped early, or still running.

Finished runs are opened with the solver's own ``diagnostics_io`` helpers.
Runs that are still in progress have no ``run_metadata.json`` yet; their grid
information comes from the ``studio_run.json`` sidecar written by the studio
worker, and only the part of each memory-mapped file that the solver has
already written is used.
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from . import solver as S

STATUS_FILE = "studio_run.json"
CONTROL_FILE = ".studio_control"
MODEL_SNAPSHOT = "studio_model.p1d.json"

TEMPORAL_FILES = {
    "V_gap": "Vgap_mm.dat",
    "V_node": "Vnode_mm.dat",
    "V_source": "Vsource_mm.dat",
    "I_discharge": "Idischarge_mm.dat",
    "I_transport_plasma": "I_transport_plasma_mm.dat",
    "I_transport_circuit": "I_transport_circuit_mm.dat",
    "I_emission_circuit": "I_emission_circuit_mm.dat",
    "I_emission_area": "I_emission_area_mm.dat",
    "I_displacement_gap": "I_displacement_gap_mm.dat",
    "cfl": "c_cfl_mm.dat",
    "diffusion_cfl": "diffusion_cfl_mm.dat",
    "picard_iterations": "picard_iterations_mm.dat",
    "adaptive_substeps": "adaptive_substeps_mm.dat",
    "adaptive_dt_sub": "adaptive_dt_sub_mm.dat",
    "adaptive_cfl_est": "adaptive_cfl_est_mm.dat",
    "adaptive_diffusion_cfl_est": "adaptive_diffusion_cfl_est_mm.dat",
}
SPATIAL_FILES = {
    "ne": "ne_sampled_mm.dat", "ni": "ni_sampled_mm.dat", "phi": "phi_sampled_mm.dat",
    "E": "E_sampled_mm.dat", "Gamma_i": "Gamma_i_sampled_mm.dat", "Gamma_e": "Gamma_e_sampled_mm.dat",
    "townsend_alpha": "townsend_alpha_sampled_mm.dat", "nu_i": "nu_i_sampled_mm.dat",
    "S_ion": "S_ion_sampled_mm.dat", "S": "S_sampled_mm.dat", "mu_e": "mu_e_sampled_mm.dat",
    "D_e": "D_e_sampled_mm.dat", "mu_i": "mu_i_sampled_mm.dat", "D_i": "D_i_sampled_mm.dat",
}
# history quantities indexed by n_idx (last entry stays 0) vs n_idx+1
_SHIFTED = {"I_discharge", "I_transport_plasma", "I_transport_circuit", "I_emission_circuit",
            "I_emission_area", "I_displacement_gap"}


def _diag_io():
    try:
        return S.import_solver_module("diagnostics_io")
    except Exception:
        return None


def write_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    for _ in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # Windows: reader holds the file for a moment
            time.sleep(0.05)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def read_json(path: Path) -> dict | None:
    for _ in range(3):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, PermissionError, OSError):
            time.sleep(0.03)
    return None


@dataclass
class RunInfo:
    path: Path
    name: str
    status: str                    # finished | running | paused | stopped | failed | aborted | incomplete
    meta: dict | None
    studio: dict | None
    mtime: float
    source: str = "studio"         # studio | notebook

    @property
    def title(self) -> str:
        if self.studio and self.studio.get("label"):
            return str(self.studio["label"])
        return self.name

    def get(self, key: str, default=None):
        if self.meta and key in self.meta:
            return self.meta[key]
        if self.studio and key in (self.studio.get("grid") or {}):
            return self.studio["grid"][key]
        if self.studio and key in (self.studio.get("config") or {}):
            return self.studio["config"][key]
        return default

    @property
    def case(self) -> str:
        if self.studio:
            return str(self.studio.get("base_case", ""))
        return ""


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        if os.name == "nt":
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if not h:
                return False
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(h)
            return code.value == 259
        os.kill(int(pid), 0)
        return True
    except (OSError, ProcessLookupError, AttributeError):
        return False


def run_status(run_dir: Path) -> tuple[str, dict | None, dict | None]:
    meta = read_json(run_dir / "run_metadata.json")
    studio = read_json(run_dir / STATUS_FILE)
    if studio:
        st = studio.get("status", "unknown")
        if st in ("running", "paused", "starting") and not _pid_alive(int(studio.get("pid") or 0)):
            st = "finished" if meta and studio.get("steps_done") == studio.get("grid", {}).get("Nt", -1) - 1 \
                else "interrupted"
        return st, meta, studio
    if meta:
        return "finished", meta, None
    return "incomplete", None, None


def discover(folders: list[Path]) -> list[RunInfo]:
    out: list[RunInfo] = []
    seen: set[Path] = set()
    for folder in folders:
        folder = Path(folder)
        if not folder.is_dir():
            continue
        try:
            children = list(folder.iterdir())
        except OSError:
            continue
        for d in children:
            if not d.is_dir():
                continue
            if not ((d / "run_metadata.json").exists() or (d / STATUS_FILE).exists()):
                continue
            rd = d.resolve()
            if rd in seen:
                continue
            seen.add(rd)
            st, meta, studio = run_status(d)
            try:
                mt = max((d / f).stat().st_mtime for f in ("run_metadata.json", STATUS_FILE) if (d / f).exists())
            except ValueError:
                mt = d.stat().st_mtime
            out.append(RunInfo(path=d, name=d.name, status=st, meta=meta, studio=studio, mtime=mt,
                               source="studio" if studio else "notebook"))
    out.sort(key=lambda r: -r.mtime)
    return out


# ---------------------------------------------------------------------------
@dataclass
class RunData:
    """Grid information + readers for one run folder."""
    run_dir: Path
    Nt: int
    Nx: int
    T_total: float
    L: float
    A: float
    save_every: int
    meta: dict
    studio: dict | None
    steps_done: int                         # last valid time index
    _cache: dict = field(default_factory=dict)

    @classmethod
    def open(cls, run_dir: str | os.PathLike, steps_done: int | None = None) -> "RunData":
        run_dir = Path(run_dir)
        st, meta, studio = run_status(run_dir)
        if meta:
            grid = dict(Nt=int(meta["Nt"]), Nx=int(meta["Nx"]), T_total=float(meta["T_total"]),
                        L=float(meta["L"]), A=float(meta.get("A", 1.0)), save_every=int(meta["save_every"]))
        elif studio and studio.get("grid"):
            g = studio["grid"]
            grid = dict(Nt=int(g["Nt"]), Nx=int(g["Nx"]), T_total=float(g["T_total"]), L=float(g["L"]),
                        A=float(g.get("A", 1.0)), save_every=int(g["save_every"]))
        else:
            raise FileNotFoundError(f"No run_metadata.json or {STATUS_FILE} in {run_dir}")
        if steps_done is None:
            if studio and studio.get("steps_done") is not None and st != "finished":
                steps_done = int(studio["steps_done"])
            elif studio and studio.get("steps_done") is not None and studio.get("stopped_early"):
                steps_done = int(studio["steps_done"])
            else:
                steps_done = grid["Nt"] - 1
        return cls(run_dir=run_dir, meta=meta or {}, studio=studio, steps_done=int(steps_done), **grid)

    # -- grids ------------------------------------------------------------------
    @property
    def dt(self) -> float:
        return self.T_total / max(self.Nt - 1, 1)

    @property
    def x(self) -> np.ndarray:
        return np.linspace(0.0, self.L, self.Nx)

    @property
    def nsave_total(self) -> int:
        return (self.Nt - 1) // self.save_every + 1

    @property
    def nsave_valid(self) -> int:
        return min(self.steps_done // self.save_every + 1, self.nsave_total)

    def snapshot_times(self) -> np.ndarray:
        k = np.arange(self.nsave_valid)
        return np.minimum(k * self.save_every, self.Nt - 1) * self.dt

    def t_valid(self) -> float:
        return self.steps_done * self.dt

    # -- availability -------------------------------------------------------
    def available_temporal(self) -> list[str]:
        names = ["V_app"] if self._v_app_func() is not None else []
        return names + [q for q, f in TEMPORAL_FILES.items() if (self.run_dir / f).exists()]

    def available_spatial(self) -> list[str]:
        return [q for q, f in SPATIAL_FILES.items() if (self.run_dir / f).exists()]

    # -- temporal -------------------------------------------------------------
    def _scalar_memmap(self, q: str):
        key = ("mm", q)
        if key in self._cache:
            return self._cache[key]
        path = self.run_dir / TEMPORAL_FILES[q]
        size = path.stat().st_size
        dtype = np.float64 if size == self.Nt * 8 else np.float32
        mm = np.memmap(path, mode="r", dtype=dtype, shape=(self.Nt,))
        self._cache[key] = mm
        return mm

    def _v_app_func(self):
        key = ("vapp",)
        if key in self._cache:
            return self._cache[key]
        func = None
        model = None
        if self.studio and self.studio.get("config"):
            model = self.studio["config"]
        try:
            if model is not None:
                func = _vapp_from_config(model)
            elif self.meta:
                dio = _diag_io()
                if dio is not None:
                    ctx = self.context()
                    func = (lambda t, _c=ctx, _d=dio: _d.reconstruct_v_app(_c, np.asarray(t)))
        except Exception:
            func = None
        self._cache[key] = func
        return func

    def context(self):
        dio = _diag_io()
        if dio is None:
            return None
        return dio.RunContext(project_dir=self.run_dir.parent, run_name=self.run_dir.name, run_dir=self.run_dir,
                              meta=self.meta or {}, Nt=self.Nt, Nx=self.Nx, T_total=self.T_total, L=self.L,
                              A=self.A, save_every=self.save_every,
                              time=np.linspace(0.0, self.T_total, self.Nt), x=self.x)

    def temporal(self, q: str, max_points: int | None = 6000, t0: float | None = None,
                 t1: float | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Return (t, y) up to the last valid step, decimated with a min/max envelope."""
        last = self.steps_done if q not in _SHIFTED else max(self.steps_done - 1, 0)
        i0 = 0 if t0 is None else max(0, int(math.floor(t0 / self.dt)))
        i1 = last if t1 is None else min(last, int(math.ceil(t1 / self.dt)))
        if i1 < i0:
            return np.empty(0), np.empty(0)
        n = i1 - i0 + 1
        if q == "V_app":
            f = self._v_app_func()
            if f is None:
                return np.empty(0), np.empty(0)
            npts = n if (max_points is None or n <= max_points) else max_points
            idx = np.unique(np.linspace(i0, i1, npts).astype(np.int64))
            t = idx * self.dt
            return t, np.asarray(f(t), dtype=float)
        mm = self._scalar_memmap(q)
        if max_points is None or n <= max_points:
            idx = np.arange(i0, i1 + 1)
            return idx * self.dt, np.asarray(mm[i0:i1 + 1], dtype=float)
        nb = max_points // 2
        block = int(math.ceil(n / nb))
        nb = n // block
        if nb < 1:
            idx = np.arange(i0, i1 + 1)
            return idx * self.dt, np.asarray(mm[i0:i1 + 1], dtype=float)
        seg = np.asarray(mm[i0:i0 + nb * block], dtype=float).reshape(nb, block)
        amin = seg.argmin(axis=1)
        amax = seg.argmax(axis=1)
        lo = np.minimum(amin, amax)
        hi = np.maximum(amin, amax)
        base = i0 + np.arange(nb) * block
        idx = np.empty(2 * nb, dtype=np.int64)
        idx[0::2] = base + lo
        idx[1::2] = base + hi
        tail = np.arange(i0 + nb * block, i1 + 1)
        idx = np.concatenate([idx, tail])
        vals = np.concatenate([np.take_along_axis(seg, lo[:, None], 1)[:, 0],
                               np.take_along_axis(seg, hi[:, None], 1)[:, 0]])
        y = np.empty(2 * nb)
        y[0::2] = vals[:nb]
        y[1::2] = vals[nb:]
        y = np.concatenate([y, np.asarray(mm[tail], dtype=float)]) if tail.size else y
        return idx * self.dt, y

    def last_value(self, q: str) -> float:
        last = self.steps_done if q not in _SHIFTED else max(self.steps_done - 1, 0)
        if q == "V_app":
            f = self._v_app_func()
            return float(f(np.array([last * self.dt]))[0]) if f else float("nan")
        return float(self._scalar_memmap(q)[last])

    # -- spatial ----------------------------------------------------------------
    def _spatial_memmap(self, q: str):
        key = ("sp", q)
        if key in self._cache:
            return self._cache[key]
        path = self.run_dir / SPATIAL_FILES[q]
        nsave = path.stat().st_size // (4 * self.Nx)
        mm = np.memmap(path, mode="r", dtype=np.float32, shape=(nsave, self.Nx))
        self._cache[key] = mm
        return mm

    def spatial(self, q: str, k: int) -> np.ndarray:
        mm = self._spatial_memmap(q)
        k = int(max(0, min(k, self.nsave_valid - 1, mm.shape[0] - 1)))
        return np.asarray(mm[k], dtype=float)

    def spatial_block(self, q: str, max_rows: int = 1500) -> tuple[np.ndarray, np.ndarray]:
        """(times, array[nt, Nx]) for space-time maps, rows decimated."""
        mm = self._spatial_memmap(q)
        n = min(self.nsave_valid, mm.shape[0])
        if n <= 0:
            return np.empty(0), np.empty((0, self.Nx))
        idx = np.unique(np.linspace(0, n - 1, min(n, max_rows)).astype(np.int64))
        times = np.minimum(idx * self.save_every, self.Nt - 1) * self.dt
        return times, np.asarray(mm[idx], dtype=float)

    def nearest_snapshot(self, t: float) -> int:
        k = int(round(t / (self.dt * self.save_every)))
        return max(0, min(k, self.nsave_valid - 1))

    def close(self):
        self._cache.clear()


def _vapp_from_config(flat_cfg: dict):
    """Rebuild V_app(t) with the solver's own make_voltage_waveform."""
    physics = S.import_solver_module("physics")
    from types import SimpleNamespace
    wf = {k.split(".", 1)[1]: v for k, v in flat_cfg.items() if k.startswith("waveform.")}
    for k, v in list(wf.items()):
        if v in ("inf", "-inf"):
            wf[k] = float(v)
    cfg = SimpleNamespace(waveform=SimpleNamespace(**wf))
    return physics.make_voltage_waveform(cfg)


# ---------------------------------------------------------------------------
def health(rd: RunData) -> dict[str, Any]:
    """Cheap numerical-health check: first non-finite time and the largest drift CFL so far."""
    out: dict[str, Any] = {"nonfinite_t": None, "cfl_max": None}
    try:
        t, V = rd.temporal("V_gap", max_points=4000)
        bad = np.where(~np.isfinite(V))[0]
        if bad.size:
            out["nonfinite_t"] = float(t[bad[0]])
        else:
            k = rd.nsave_valid - 1
            if "ne" in rd.available_spatial() and k >= 0 and not np.all(np.isfinite(rd.spatial("ne", k))):
                out["nonfinite_t"] = float(rd.snapshot_times()[k])
    except Exception:
        pass
    try:
        _, c = rd.temporal("cfl", max_points=4000)
        c = c[np.isfinite(c)]
        if c.size:
            out["cfl_max"] = float(c.max())
    except Exception:
        pass
    return out


def health_message(h: dict, adaptive: bool | None = None) -> str:
    from .units import format_quantity
    if h.get("nonfinite_t") is not None:
        return (f"The solution became non-finite (NaN/Inf) at t ≈ {format_quantity(h['nonfinite_t'], 's')}. "
                "The time step is too large for this grid and field: enable adaptive sub-stepping, increase Nt "
                "(smaller dt) or refine the grid, then run again.")
    c = h.get("cfl_max")
    if c is not None and c > 1.0:
        return (f"The drift CFL number reached {c:.3g} (> 1). Results may be inaccurate or unstable – "
                "enable adaptive sub-stepping or increase Nt.")
    return ""


def summary_metrics(rd: RunData) -> dict[str, Any]:
    """Compact, robust numbers that describe a run (used by lists and sweeps)."""
    out: dict[str, Any] = {}
    try:
        t, I = rd.temporal("I_discharge", max_points=None)
        if I.size:
            k = int(np.nanargmax(np.abs(np.where(np.isfinite(I), I, 0.0))))
            out["I_peak_A"] = float(I[k])
            out["t_I_peak_s"] = float(t[k])
            out["I_final_A"] = float(I[-1])
            out["charge_C"] = float(np.trapezoid(I, t) if hasattr(np, "trapezoid") else np.trapz(I, t))
    except Exception:
        pass
    try:
        t, V = rd.temporal("V_gap", max_points=None)
        if V.size:
            k = int(np.nanargmin(np.where(np.isfinite(V), V, np.nan))) if np.isfinite(V).any() else 0
            out["V_gap_min_V"] = float(V[k])
            out["t_V_gap_min_s"] = float(t[k])
            out["V_gap_max_V"] = float(np.nanmax(V))
            out["V_gap_final_V"] = float(V[-1])
    except Exception:
        pass
    try:
        k = rd.nsave_valid - 1
        if "ne" in rd.available_spatial():
            mm = rd._spatial_memmap("ne")
            ne_max = np.asarray(mm[:rd.nsave_valid].max(axis=1), dtype=float)
            j = int(np.argmax(ne_max))
            out["ne_max_m3"] = float(ne_max[j])
            out["t_ne_max_s"] = float(rd.snapshot_times()[j])
            out["ne_final_max_m3"] = float(np.max(rd.spatial("ne", k)))
            x = rd.x
            ne_mid = float(rd.spatial("ne", k)[len(x) // 2])
            out["ne_mid_final_m3"] = ne_mid
    except Exception:
        pass
    try:
        _, cfl = rd.temporal("cfl", max_points=None)
        cfl = cfl[np.isfinite(cfl)]
        if cfl.size:
            out["cfl_max"] = float(np.max(cfl))
    except Exception:
        pass
    try:
        t, V = rd.temporal("V_gap", max_points=None)
        bad = np.where(~np.isfinite(V))[0]
        if bad.size:
            out["nonfinite_t_s"] = float(t[bad[0]])
    except Exception:
        pass
    return out


METRIC_LABELS = {
    "I_peak_A": ("Peak current", "A"),
    "t_I_peak_s": ("Time of peak current", "s"),
    "I_final_A": ("Final current", "A"),
    "charge_C": ("Transferred charge", "C"),
    "V_gap_min_V": ("Minimum gap voltage", "V"),
    "t_V_gap_min_s": ("Time of minimum V_gap", "s"),
    "V_gap_max_V": ("Maximum gap voltage", "V"),
    "V_gap_final_V": ("Final gap voltage", "V"),
    "ne_max_m3": ("Peak electron density", "m⁻³"),
    "t_ne_max_s": ("Time of peak nₑ", "s"),
    "ne_final_max_m3": ("Final peak nₑ", "m⁻³"),
    "ne_mid_final_m3": ("Final mid-gap nₑ", "m⁻³"),
    "cfl_max": ("Max drift CFL", ""),
    "nonfinite_t_s": ("Became non-finite at", "s"),
}
