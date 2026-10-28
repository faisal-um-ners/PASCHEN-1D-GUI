"""Locate and talk to the PASCHEN-1D solver without modifying it.

Everything the studio knows about the solver is discovered at run time:

* the solver folder (``find_solver_root``),
* the available case modules (``list_cases``),
* the complete configuration schema, including the explanatory comments that
  sit above every field in ``config.py`` (``load_schema``).

Only public, read-only entry points of PASCHEN-1D are used.
"""
from __future__ import annotations

import ast
import dataclasses
import importlib
import importlib.util
import os
import re
import sys
import typing
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT_MARKERS = ("paschen_1d.py", "config_loader.py", "config.py", "data_paths.py")
ENV_VAR = "PASCHEN1D_HOME"

_ROOT: Path | None = None
_EXTRA_CASE_DIRS: list[Path] = []


# ---------------------------------------------------------------------------
# Locating the solver
# ---------------------------------------------------------------------------
def is_solver_root(path: str | os.PathLike | None) -> bool:
    if not path:
        return False
    p = Path(path)
    return p.is_dir() and all((p / m).is_file() for m in ROOT_MARKERS)


def studio_dir() -> Path:
    """Folder that contains the ``paschen_studio`` package (``studio/``)."""
    return Path(__file__).resolve().parent.parent


def candidate_roots(explicit: str | None = None) -> list[Path]:
    cands: list[Path] = []
    if explicit:
        cands.append(Path(explicit).expanduser())
    env = os.environ.get(ENV_VAR)
    if env:
        cands.append(Path(env).expanduser())
    here = studio_dir()
    cands += [here.parent, here, Path.cwd(), Path.cwd().parent]
    # An installed (non-editable) PASCHEN-1D wheel puts the modules in site-packages.
    spec = importlib.util.find_spec("paschen_1d") if "paschen_1d" not in sys.modules else None
    if spec is not None and spec.origin:
        cands.append(Path(spec.origin).resolve().parent)
    elif "paschen_1d" in sys.modules and getattr(sys.modules["paschen_1d"], "__file__", None):
        cands.append(Path(sys.modules["paschen_1d"].__file__).resolve().parent)
    return cands


def find_solver_root(explicit: str | None = None) -> Path | None:
    for c in candidate_roots(explicit):
        try:
            if is_solver_root(c):
                return c.resolve()
        except OSError:
            continue
    return None


def cache_dir() -> Path:
    """Folder for Python byte-code and Numba caches (keeps the solver folder untouched)."""
    for cand in (studio_dir() / ".cache", Path.home() / ".cache" / "paschen-studio"):
        try:
            cand.mkdir(parents=True, exist_ok=True)
            probe = cand / ".w"
            probe.write_text("ok")
            probe.unlink()
            return cand
        except OSError:
            continue
    return Path.cwd()


def isolate_caches() -> None:
    """Redirect __pycache__ and Numba's on-disk cache away from the PASCHEN-1D folder.

    Importing the solver normally writes ``__pycache__`` (and Numba ``cache=True``
    kernels) next to the solver sources.  The studio sends these to its own
    cache folder instead, so running the GUI leaves the solver tree exactly as it
    was.  Applies to this process and, through the environment, to workers.
    """
    c = cache_dir()
    os.environ.setdefault("NUMBA_CACHE_DIR", str(c / "numba"))
    os.environ.setdefault("PYTHONPYCACHEPREFIX", str(c / "pycache"))
    if getattr(sys, "pycache_prefix", None) is None:
        sys.pycache_prefix = str(c / "pycache")


def set_solver_root(path: str | os.PathLike) -> Path:
    """Select the solver folder and make its modules importable."""
    global _ROOT
    p = Path(path).expanduser().resolve()
    if not is_solver_root(p):
        raise FileNotFoundError(
            f"'{p}' does not look like a PASCHEN-1D folder (missing one of {', '.join(ROOT_MARKERS)})."
        )
    isolate_caches()
    if _ROOT is not None and _ROOT != p:
        # switching solver folders: forget modules imported from the old one
        for name in list(sys.modules):
            mod = sys.modules[name]
            f = getattr(mod, "__file__", None)
            if f and Path(f).resolve().parent == _ROOT:
                del sys.modules[name]
        try:
            sys.path.remove(str(_ROOT))
        except ValueError:
            pass
        load_schema.cache_clear()
        case_defaults.cache_clear()
    _ROOT = p
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
    return p


def solver_root(required: bool = True) -> Path | None:
    global _ROOT
    if _ROOT is None:
        found = find_solver_root()
        if found is not None:
            set_solver_root(found)
    if _ROOT is None and required:
        raise FileNotFoundError(
            "PASCHEN-1D was not found. Put the 'studio' folder inside the PASCHEN-1D folder, "
            f"set the {ENV_VAR} environment variable, or choose the folder in the GUI."
        )
    return _ROOT


def add_case_dir(path: str | os.PathLike) -> None:
    p = Path(path).expanduser().resolve()
    if p.is_dir() and p not in _EXTRA_CASE_DIRS:
        _EXTRA_CASE_DIRS.append(p)
        if str(p) not in sys.path:
            sys.path.append(str(p))


def import_solver_module(name: str):
    solver_root()
    return importlib.import_module(name)


def solver_version() -> tuple[str, str]:
    try:
        v = import_solver_module("version")
        return str(getattr(v, "__version__", "?")), str(getattr(v, "__release_date__", ""))
    except Exception:  # pragma: no cover - defensive
        return "?", ""


# ---------------------------------------------------------------------------
# Case modules
# ---------------------------------------------------------------------------
@dataclass
class CaseInfo:
    module: str
    file: Path
    title: str
    summary: str
    details: str
    tags: list[str] = field(default_factory=list)
    builtin: bool = True


# Friendly descriptions for the shipped cases (fallback: parsed docstring).
KNOWN_CASES: dict[str, dict[str, Any]] = {
    "config_case_argon_photoemission_discharge": dict(
        title="Argon photoemission-triggered discharge",
        summary="231 V step on a 3.5 mm argon gap (2.86 Torr); a 30 ps UV laser pulse on the "
                "cathode seeds the discharge. R0-Rm-Cext circuit.",
        tags=["Argon", "Step drive", "Photoemission", "R0-Rm-Cext"]),
    "config_case_argon_dc_discharge": dict(
        title="Argon DC glow discharge",
        summary="140 V DC across a 3.5 mm argon gap at 2.88 Torr with ion-induced secondary "
                "emission (gamma = 0.05). Classic breakdown-to-glow transient.",
        tags=["Argon", "DC", "Secondary emission", "R0-Rm-Cext"]),
    "config_case_nitrogen_pulsed_discharge": dict(
        title="Nitrogen nanosecond pulsed DBD",
        summary="20 kV, 15 ns Gaussian pulse across a 1 cm nitrogen gap (60 Torr) with quartz "
                "dielectric layers. Benchmark of the paper (Adamovich et al.).",
        tags=["Nitrogen", "Gaussian pulse", "Dielectric barrier", "ns"]),
    "config_case_deuterium_pulsed_discharge": dict(
        title="Deuterium nanosecond pulsed DBD",
        summary="Same dielectric-barrier pulse in D2, using BOLSIG+ electron tables and a matched "
                "LXCat D3+/D2 ion mobility/diffusion pair.",
        tags=["Deuterium", "Gaussian pulse", "Swarm tables", "LXCat ions"]),
    "config_case_helium_photoemission_discharge": dict(
        title="Helium photoemission discharge",
        summary="Helium version of the photoemission transient with BOLSIG+ electron data, "
                "LXCat He+ mobility and Einstein-relation ion diffusion.",
        tags=["Helium", "Step drive", "Photoemission", "Swarm tables"]),
    "config": dict(
        title="Generic guided configuration",
        summary="The fully commented generic configuration (argon photoemission defaults).",
        tags=["Template", "Argon"]),
}

CASE_ORDER = [
    "config_case_nitrogen_pulsed_discharge",
    "config_case_argon_dc_discharge",
    "config_case_argon_photoemission_discharge",
    "config_case_deuterium_pulsed_discharge",
    "config_case_helium_photoemission_discharge",
    "config",
]


def _docstring_parts(path: Path) -> tuple[str, str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        doc = ast.get_docstring(tree) or ""
    except Exception:
        return "", ""
    paras = [p.strip() for p in re.split(r"\n\s*\n", doc) if p.strip()]
    paras = [p for p in paras if not p.endswith(".py")]
    summary = paras[0] if paras else ""
    details = ""
    for p in paras[1:]:
        if p.startswith("The ") and ("case" in p or "default" in p):
            details = " ".join(p.split())
            break
    return " ".join(summary.split()), details


def _humanize_module(name: str) -> str:
    n = name.replace("config_case_", "").replace("_", " ").strip()
    return n[:1].upper() + n[1:] if n else name


def list_cases() -> list[CaseInfo]:
    root = solver_root()
    files: list[tuple[Path, bool]] = []
    for f in sorted(root.glob("config_case_*.py")):
        files.append((f, True))
    if (root / "config.py").is_file():
        files.append((root / "config.py", True))
    for d in _EXTRA_CASE_DIRS:
        for f in sorted(d.glob("*.py")):
            if f.name.startswith("config") and f not in [x for x, _ in files]:
                files.append((f, False))
    out: list[CaseInfo] = []
    for f, builtin in files:
        mod = f.stem
        known = KNOWN_CASES.get(mod) if builtin else None
        summary, details = _docstring_parts(f)
        out.append(CaseInfo(
            module=mod, file=f,
            title=(known or {}).get("title") or _humanize_module(mod),
            summary=(known or {}).get("summary") or details or summary,
            details=details or summary,
            tags=list((known or {}).get("tags", [])),
            builtin=builtin,
        ))
    order = {m: i for i, m in enumerate(CASE_ORDER)}
    out.sort(key=lambda c: (order.get(c.module, 100), c.module))
    return out


def case_module(name: str):
    """Import a case module through the solver's own loader."""
    solver_root()
    loader = importlib.import_module("config_loader")
    return loader.load_config_module(name)


@lru_cache(maxsize=32)
def case_defaults(name: str) -> dict[str, Any]:
    """Flat ``{path: default}`` dictionary for a case module."""
    cfg = case_module(name).SimulationConfig()
    return flatten_config(cfg)


def flatten_config(obj, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in dataclasses.fields(obj):
        v = getattr(obj, f.name)
        p = f"{prefix}{f.name}"
        if dataclasses.is_dataclass(v):
            out.update(flatten_config(v, p + "."))
        else:
            out[p] = v
    return out


# ---------------------------------------------------------------------------
# Schema introspection
# ---------------------------------------------------------------------------
@dataclass
class FieldInfo:
    path: str
    group: str
    name: str
    kind: str                      # float int bool str choice optional_str optional_float
    #                                multichoice float_tuple_opt python
    choices: list[str] | None
    optional: bool
    comment: str
    type_repr: str


@dataclass
class GroupInfo:
    path: str
    class_name: str
    doc: str                       # class docstring
    guide: str                     # markdown cell above the class in config.py
    fields: list[FieldInfo]


@dataclass
class Schema:
    groups: dict[str, GroupInfo]
    fields: dict[str, FieldInfo]
    case: str

    def group_of(self, path: str) -> str:
        return self.fields[path].group


def _strip_comment(line: str) -> str:
    s = line.strip()
    if s.startswith("#"):
        s = s[1:]
        if s.startswith(" "):
            s = s[1:]
    return s.rstrip()


def _source_comments(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, str], dict[str, str]]:
    """Return ({class: {field: comment}}, {class: markdown guide}, {class: docstring})."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    tree = ast.parse(text)
    fields: dict[str, dict[str, str]] = {}
    guides: dict[str, str] = {}
    docs: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        docs[node.name] = ast.get_docstring(node) or ""
        # markdown cell above the decorator / class line
        start = (node.decorator_list[0].lineno if node.decorator_list else node.lineno) - 2
        i = start
        while i >= 0 and lines[i].strip() in ("", "# %%"):
            i -= 1
        md: list[str] = []
        while i >= 0 and lines[i].lstrip().startswith("#"):
            if lines[i].strip().startswith("# %% [markdown]"):
                break
            md.append(_strip_comment(lines[i]))
            i -= 1
        if i >= 0 and lines[i].strip().startswith("# %% [markdown]"):
            guides[node.name] = "\n".join(reversed(md)).strip()
        per: dict[str, str] = {}
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                j = item.lineno - 2
                com: list[str] = []
                while j >= 0 and lines[j].lstrip().startswith("#"):
                    com.append(_strip_comment(lines[j]))
                    j -= 1
                per[item.target.id] = "\n".join(reversed(com)).strip()
        fields[node.name] = per
    return fields, guides, docs


def _kind_of(tp) -> tuple[str, list[str] | None, bool, str]:
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    rep = getattr(tp, "__name__", None) or repr(tp).replace("typing.", "")
    if tp is bool:
        return "bool", None, False, "bool"
    if tp is int:
        return "int", None, False, "int"
    if tp is float:
        return "float", None, False, "float"
    if tp is str:
        return "str", None, False, "str"
    if origin is typing.Literal:
        return "choice", [str(a) for a in args], False, rep
    union_types = (typing.Union,)
    try:
        import types as _types
        union_types = (typing.Union, _types.UnionType)
    except AttributeError:  # pragma: no cover
        pass
    if origin in union_types:
        non_none = [a for a in args if a is not type(None)]
        optional = len(non_none) < len(args)
        if len(non_none) == 1:
            k, ch, _, _ = _kind_of(non_none[0])
            if k == "str":
                return "optional_str", None, optional, rep
            if k in ("float", "int"):
                return "optional_float", None, optional, rep
            if k == "float_tuple":
                return "float_tuple_opt", None, optional, rep
            if k == "choice":
                return "choice", ch, optional, rep
            return "python", None, optional, rep
        return "python", None, optional, rep
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            inner = args[0]
            if typing.get_origin(inner) is typing.Literal:
                return "multichoice", [str(a) for a in typing.get_args(inner)], False, rep
            if inner in (float, int):
                return "float_tuple", None, False, rep
        return "python", None, False, rep
    return "python", None, False, rep


@lru_cache(maxsize=16)
def load_schema(case: str = "config") -> Schema:
    mod = case_module(case)
    src = Path(mod.__file__)
    comments, guides, docs = _source_comments(src)
    groups: dict[str, GroupInfo] = {}
    fields: dict[str, FieldInfo] = {}

    def walk(cls, prefix: str):
        try:
            hints = typing.get_type_hints(cls, globalns=vars(mod))
        except Exception:
            hints = {f.name: f.type for f in dataclasses.fields(cls)}
        gpath = prefix.rstrip(".")
        ginfo = GroupInfo(path=gpath, class_name=cls.__name__, doc=docs.get(cls.__name__, ""),
                          guide=guides.get(cls.__name__, ""), fields=[])
        if gpath:
            groups[gpath] = ginfo
        for f in dataclasses.fields(cls):
            tp = hints.get(f.name, f.type)
            if dataclasses.is_dataclass(tp):
                walk(tp, prefix + f.name + ".")
                continue
            kind, choices, optional, rep = _kind_of(tp)
            fi = FieldInfo(path=prefix + f.name, group=gpath, name=f.name, kind=kind, choices=choices,
                           optional=optional, comment=comments.get(cls.__name__, {}).get(f.name, ""),
                           type_repr=rep)
            ginfo.fields.append(fi)
            fields[fi.path] = fi

    walk(mod.SimulationConfig, "")
    return Schema(groups=groups, fields=fields, case=case)


# ---------------------------------------------------------------------------
# Swarm-data catalogues (read-only)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def electron_tables() -> list[dict[str, Any]]:
    import json
    p = solver_root() / "electron_swarm_data" / "manifest.json"
    try:
        man = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for t in man.get("tables", []):
        fn = t.get("filename", "")
        out.append(dict(t, basename=Path(fn).name))
    out.sort(key=lambda t: t.get("gas", ""))
    return out


@lru_cache(maxsize=1)
def ion_manifest() -> dict[str, Any]:
    import json
    root = solver_root() / "ion_swarm_data"
    cands = sorted(root.glob("normalized_lxcat_*/manifest.json"))
    if not cands:
        return {}
    try:
        return json.loads(cands[-1].read_text(encoding="utf-8"))
    except Exception:
        return {}


def canonical_gas(name: str) -> str:
    try:
        it = import_solver_module("ion_transport")
        return it.canonical_neutral(name)
    except Exception:
        return re.sub(r"[^a-z0-9]", "", str(name).lower())


def canonical_ion(name: str) -> str:
    try:
        it = import_solver_module("ion_transport")
        return it.canonical_ion(name)
    except Exception:
        return re.sub(r"[\s^{}()]", "", str(name)).lower()


def _elements(formula: str) -> set[str]:
    s = re.sub(r"\(.*?\)", "", str(formula))       # drop state labels such as (2P1/2)
    s = re.sub(r"^\d+", "", s)                       # drop a leading isotope number
    return set(re.findall(r"[A-Z][a-z]?", s))


def ion_is_native(ion: str, neutral: str) -> bool:
    """True for the gas's own ions (Ar+ in Ar, N4+ in N2, D3+ in D2 ...)."""
    ie, ne = _elements(ion), _elements(neutral)
    if not ne:
        return False
    if ie <= ne:
        return True
    # isotopic hydrogen: D/H/T are the same element for this purpose
    hyd = {"H", "D", "T"}
    return bool(ie) and ie <= hyd and ne <= hyd


def _ion_rank(rec: dict[str, Any], neutral_key: str, lo_key: str, hi_key: str) -> tuple:
    ion = str(rec.get("ion", ""))
    native = ion_is_native(ion, str(rec.get("neutral", "")))
    plain = "(" not in ion and not re.match(r"^\d", ion)
    import math as _m
    lo = max(float(rec.get(lo_key, 1e-9) or 1e-9), 1e-9)
    hi = max(float(rec.get(hi_key, 0) or 0), lo)
    # overlap (in decades) with the typical discharge range 10 - 1000 Td, then total span
    overlap = max(0.0, _m.log10(min(hi, 1000.0)) - _m.log10(max(lo, 10.0)))
    return (not native, not plain, -round(overlap, 2), -_m.log10(hi / lo))


def ion_pairs_for_gas(gas: str, native_only: bool = False) -> list[dict[str, Any]]:
    man = ion_manifest()
    key = canonical_gas(gas)
    out = []
    for p in man.get("compatible_mobility_diffusion_pairs", []):
        ion = str(p.get("ion", ""))
        if canonical_gas(p.get("neutral", "")) != key:
            continue
        if "+" not in ion or "-" in ion:
            continue
        if native_only and not ion_is_native(ion, str(p.get("neutral", ""))):
            continue
        out.append(p)
    out.sort(key=lambda p: _ion_rank(p, key, "common_reduced_field_min_Td", "common_reduced_field_max_Td"))
    return out


def ion_mobility_tables_for_gas(gas: str) -> list[dict[str, Any]]:
    man = ion_manifest()
    key = canonical_gas(gas)
    out = []
    for r in man.get("records", []):
        if not r.get("normalized_file"):
            continue
        if canonical_gas(r.get("neutral", "")) != key:
            continue
        ion = str(r.get("ion", ""))
        if "+" not in ion or "-" in ion:
            continue
        if "mobility" not in str(r.get("normalized_file", "")):
            continue
        out.append(r)
    out.sort(key=lambda r: _ion_rank(r, key, "axis_min", "axis_max"))
    return out


def known_gases() -> list[tuple[str, str]]:
    """``[(config_gas_value, display)]`` for gases with bundled electron tables."""
    names = {
        "ar": "argon", "n2": "nitrogen", "d2": "deuterium", "h2": "hydrogen", "he": "helium",
        "ne": "neon", "kr": "krypton", "xe": "xenon", "o2": "oxygen",
    }
    seen = {}
    for t in electron_tables():
        c = str(t.get("canonical_gas", "")).lower()
        if not c or c in seen:
            continue
        formula = str(t.get("gas", c))
        seen[c] = (names.get(c, formula), formula)
    out = [(v, f"{v}  ({g})" if v != g else v) for c, (v, g) in seen.items()]
    out.sort(key=lambda x: (x[0] not in ("argon", "nitrogen", "helium", "deuterium"), x[0]))
    return out


def has_empirical_closures(gas: str) -> bool:
    return canonical_gas(gas) in ("ar", "n2")
