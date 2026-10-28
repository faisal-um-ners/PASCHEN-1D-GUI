"""Studio model = a PASCHEN-1D case module + the settings the user changed.

A model file (``*.p1d.json``) stores only the *base case* and the *overrides*,
so it stays small, readable and robust to new solver defaults::

    {
      "format": "paschen-studio-model/1",
      "title": "Argon breakdown at 160 V",
      "base_case": "config_case_argon_dc_discharge",
      "overrides": {"waveform.V_peak": 160.0, "run.run_name": "argon_160V"},
      "sweep": {"parameter": "waveform.V_peak", "values": [140, 160, 180]}
    }

``StudioModel.build_config()`` creates a real ``SimulationConfig`` from the case
module and applies the overrides - exactly what a user would type in the run
notebook after ``cfg = SimulationConfig()``.
"""
from __future__ import annotations

import copy
import dataclasses
import datetime as _dt
import json
import math
import os
from pathlib import Path
from typing import Any

from . import MODEL_FORMAT, __version__
from . import solver as S


# ---------------------------------------------------------------------------
# JSON helpers (infinity, tuples)
# ---------------------------------------------------------------------------
def to_jsonable(v):
    if isinstance(v, float):
        if math.isinf(v):
            return "inf" if v > 0 else "-inf"
        if math.isnan(v):
            return "nan"
        return v
    if isinstance(v, (list, tuple)):
        return [to_jsonable(x) for x in v]
    if hasattr(v, "item") and callable(v.item):  # numpy scalar
        try:
            return to_jsonable(v.item())
        except Exception:
            return str(v)
    return v


def from_jsonable(v, like=None, kind: str | None = None):
    if isinstance(v, str) and v in ("inf", "-inf", "nan") and kind not in ("str", "optional_str", "choice"):
        return float(v)
    if isinstance(v, list):
        return tuple(from_jsonable(x) for x in v)
    if kind in ("float", "optional_float") and isinstance(v, int) and not isinstance(v, bool):
        return float(v)
    return v


def values_equal(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b or a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        fa, fb = float(a), float(b)
        if math.isnan(fa) and math.isnan(fb):
            return True
        if math.isinf(fa) or math.isinf(fb):
            return fa == fb
        return math.isclose(fa, fb, rel_tol=1e-12, abs_tol=0.0) or fa == fb
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(values_equal(x, y) for x, y in zip(a, b))
    return a == b


def py_literal(v) -> str:
    """Python source for a configuration value (used by the script exporter)."""
    if isinstance(v, float):
        if math.isinf(v):
            return "float('inf')" if v > 0 else "-float('inf')"
        if math.isnan(v):
            return "float('nan')"
        return repr(v)
    if isinstance(v, tuple):
        inner = ", ".join(py_literal(x) for x in v)
        return f"({inner},)" if len(v) == 1 else f"({inner})"
    return repr(v)


# ---------------------------------------------------------------------------
class StudioModel:
    """Base case + overrides, with change tracking and an undo history."""

    def __init__(self, base_case: str = "config_case_argon_dc_discharge", overrides: dict | None = None,
                 title: str = "", description: str = ""):
        self.base_case = base_case
        self.base_case_dir: str | None = None
        self.overrides: dict[str, Any] = {}
        self.title = title
        self.description = description
        self.notes = ""
        self.sweep: dict | None = None
        self.path: Path | None = None
        self.created = _dt.datetime.now().isoformat(timespec="seconds")
        self.modified = self.created
        self._undo: list[tuple[str, Any, Any]] = []
        self._redo: list[tuple[str, Any, Any]] = []
        for k, v in (overrides or {}).items():
            self.overrides[k] = v

    # -- case ---------------------------------------------------------------
    @property
    def schema(self) -> S.Schema:
        return S.load_schema(self.base_case)

    def defaults(self) -> dict[str, Any]:
        return S.case_defaults(self.base_case)

    def values(self) -> dict[str, Any]:
        v = dict(self.defaults())
        v.update(self.overrides)
        return v

    def value(self, path: str):
        if path in self.overrides:
            return self.overrides[path]
        return self.defaults().get(path)

    def default(self, path: str):
        return self.defaults().get(path)

    def is_modified(self, path: str) -> bool:
        return path in self.overrides

    def set(self, path: str, value, record: bool = True) -> bool:
        """Set a value; returns True when something changed."""
        old = self.value(path)
        if values_equal(old, value) and type(old) is type(value):
            return False
        if values_equal(self.default(path), value) and type(self.default(path)) is type(value):
            self.overrides.pop(path, None)
        else:
            self.overrides[path] = value
        if record:
            self._undo.append((path, old, value))
            self._redo.clear()
        self.modified = _dt.datetime.now().isoformat(timespec="seconds")
        return True

    def reset(self, path: str) -> bool:
        if path not in self.overrides:
            return False
        return self.set(path, self.default(path))

    def reset_group(self, group: str) -> list[str]:
        changed = [p for p in list(self.overrides) if p.rpartition(".")[0] == group]
        for p in changed:
            self.set(p, self.default(p))
        return changed

    def undo(self) -> str | None:
        if not self._undo:
            return None
        path, old, new = self._undo.pop()
        self.set(path, old, record=False)
        self._redo.append((path, old, new))
        return path

    def redo(self) -> str | None:
        if not self._redo:
            return None
        path, old, new = self._redo.pop()
        self.set(path, new, record=False)
        self._undo.append((path, old, new))
        return path

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def change_case(self, new_case: str, keep_overrides: bool = True) -> None:
        """Switch the base case; overrides that still apply are kept."""
        old_vals = self.values()
        self.base_case = new_case
        new_defaults = self.defaults()
        if keep_overrides:
            self.overrides = {k: v for k, v in self.overrides.items()
                              if k in new_defaults and not values_equal(new_defaults[k], v)}
        else:
            self.overrides = {}
        del old_vals
        self._undo.clear()
        self._redo.clear()

    # -- names ----------------------------------------------------------------
    @property
    def run_name(self) -> str:
        return str(self.value("run.run_name"))

    def display_title(self) -> str:
        if self.title:
            return self.title
        if self.path:
            return Path(self.path).name.replace(".p1d.json", "")
        return "Untitled model"

    # -- building ---------------------------------------------------------------
    def build_config(self, extra: dict | None = None):
        """Return a ready-to-run ``SimulationConfig`` instance."""
        if self.base_case_dir:
            S.add_case_dir(self.base_case_dir)
        mod = S.case_module(self.base_case)
        cfg = mod.SimulationConfig()
        ov = dict(self.overrides)
        if extra:
            ov.update(extra)
        for path, val in ov.items():
            apply_override(cfg, path, val)
        return cfg

    # -- serialisation ---------------------------------------------------------
    def to_dict(self) -> dict:
        d = {
            "format": MODEL_FORMAT,
            "studio_version": __version__,
            "solver_version": S.solver_version()[0],
            "title": self.title,
            "description": self.description,
            "base_case": self.base_case,
            "overrides": {k: to_jsonable(v) for k, v in sorted(self.overrides.items())},
            "created": self.created,
            "modified": self.modified,
        }
        if self.base_case_dir:
            d["base_case_dir"] = self.base_case_dir
        if self.notes:
            d["notes"] = self.notes
        if self.sweep:
            d["sweep"] = to_jsonable(self.sweep)
        return d

    @classmethod
    def from_dict(cls, d: dict, path: str | os.PathLike | None = None) -> "StudioModel":
        fmt = d.get("format", MODEL_FORMAT)
        if not str(fmt).startswith("paschen-studio-model"):
            raise ValueError(f"Not a PASCHEN-1D Studio model file (format = {fmt!r}).")
        m = cls(base_case=d.get("base_case", "config"), title=d.get("title", ""),
                description=d.get("description", ""))
        m.base_case_dir = d.get("base_case_dir")
        if m.base_case_dir:
            bdir = Path(m.base_case_dir)
            if not bdir.is_absolute() and path is not None:
                bdir = (Path(path).parent / bdir).resolve()
            m.base_case_dir = str(bdir)
            S.add_case_dir(bdir)
        m.notes = d.get("notes", "")
        m.sweep = d.get("sweep")
        m.created = d.get("created", m.created)
        m.modified = d.get("modified", m.modified)
        schema = m.schema
        unknown = []
        for k, v in (d.get("overrides") or {}).items():
            fi = schema.fields.get(k)
            if fi is None:
                unknown.append(k)
                continue
            m.overrides[k] = from_jsonable(v, kind=fi.kind)
        m.unknown_overrides = unknown
        if path is not None:
            m.path = Path(path)
        return m

    def save(self, path: str | os.PathLike | None = None) -> Path:
        p = Path(path or self.path)
        if not str(p).endswith(".json"):
            p = p.with_name(p.name + ".p1d.json")
        self.modified = _dt.datetime.now().isoformat(timespec="seconds")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self.path = p
        return p

    @classmethod
    def load(cls, path: str | os.PathLike) -> "StudioModel":
        p = Path(path)
        d = json.loads(p.read_text(encoding="utf-8"))
        return cls.from_dict(d, path=p)

    def copy(self) -> "StudioModel":
        m = StudioModel.from_dict(copy.deepcopy(self.to_dict()))
        m.path = self.path
        return m

    # -- exports ---------------------------------------------------------------
    def to_python_script(self, solver_root: str | None = None) -> str:
        root = solver_root or str(S.solver_root())
        lines = [
            '"""PASCHEN-1D run script generated by PASCHEN-1D Studio.',
            "",
            f"Model : {self.display_title()}",
            f"Case  : {self.base_case}",
            f"Date  : {_dt.datetime.now():%Y-%m-%d %H:%M}",
            "",
            "Run it from any folder:  python this_script.py",
            "Results are written to ./<run_name>/ (relative to the current folder).",
            '"""',
            "import sys",
            "",
            "# Folder that contains paschen_1d.py (edit if you move this script to another machine).",
            f"PASCHEN1D_HOME = {root!r}",
            "sys.path.insert(0, PASCHEN1D_HOME)",
        ]
        if self.base_case_dir:
            lines.append(f"sys.path.insert(0, {self.base_case_dir!r})")
        lines += [
            "",
            "from config_loader import load_simulation_case",
            "",
            f"SimulationConfig, run_simulation = load_simulation_case({self.base_case!r})",
            "cfg = SimulationConfig()",
            "",
            "# Settings changed in PASCHEN-1D Studio",
        ]
        for k, v in sorted(self.overrides.items()):
            lines.append(f"cfg.{k} = {py_literal(v)}")
        if not self.overrides:
            lines.append("# (none - case defaults)")
        lines += [
            "",
            "if __name__ == '__main__':",
            "    state = run_simulation(cfg)",
            "    print(f'Saved run outputs in: {cfg.run.run_name}')",
            "",
        ]
        return "\n".join(lines)

    def summary_rows(self) -> list[tuple[str, str, str]]:
        """``[(path, default, value)]`` for every changed setting."""
        from .units import format_quantity
        from .schema import meta_for
        rows = []
        for k in sorted(self.overrides):
            meta = meta_for(k, self.schema.fields.get(k).comment if k in self.schema.fields else "")
            rows.append((k, format_quantity(self.default(k), meta.unit) if isinstance(self.default(k), float)
                         else str(self.default(k)),
                         format_quantity(self.value(k), meta.unit) if isinstance(self.value(k), float)
                         else str(self.value(k))))
        return rows


# ---------------------------------------------------------------------------
def apply_override(cfg, path: str, value) -> None:
    parts = path.split(".")
    obj = cfg
    for p in parts[:-1]:
        obj = getattr(obj, p)
    name = parts[-1]
    if not hasattr(obj, name):
        raise AttributeError(f"Unknown setting '{path}'")
    cur = getattr(obj, name)
    if isinstance(value, list):
        value = tuple(value)
    if isinstance(cur, float) and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    if isinstance(value, str) and value in ("inf", "-inf") and isinstance(cur, float):
        value = float(value)
    setattr(obj, name, value)


def config_to_dict(cfg) -> dict:
    out = {}
    for k, v in S.flatten_config(cfg).items():
        out[k] = to_jsonable(v)
    return out


def new_model_from_case(case: str) -> StudioModel:
    m = StudioModel(base_case=case)
    info = next((c for c in S.list_cases() if c.module == case), None)
    m.title = info.title if info else case
    m.description = info.summary if info else ""
    return m


def unique_run_name(base: str, workspace: Path) -> str:
    base = base.strip() or "run"
    if not (workspace / base).exists():
        return base
    i = 2
    while (workspace / f"{base}_{i}").exists():
        i += 1
    return f"{base}_{i}"


def dataclass_fields(obj) -> list[str]:
    return [f.name for f in dataclasses.fields(obj)]
