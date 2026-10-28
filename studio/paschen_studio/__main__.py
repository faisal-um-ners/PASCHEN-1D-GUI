"""Command-line interface:  python -m paschen_studio <command> ...

Commands
  gui    [model.p1d.json]                 start the graphical user interface (default)
  run    model.p1d.json [options]         run a model in the terminal (live progress bar)
  sweep  model.p1d.json [options]         run the parameter sweep stored in the model
  check  model.p1d.json                   validate a model (solver validation + advice)
  cases                                   list the PASCHEN-1D case modules
  new    CASE out.p1d.json                create a model file from a case module
  export-script model.p1d.json out.py     write a plain Python script that runs the model
  results [folder]                        list run folders with their status
  info                                    versions, paths, threads
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _setup_solver(root: str | None):
    from . import solver as S
    found = S.find_solver_root(root)
    if found is None:
        print("✖ PASCHEN-1D was not found.\n  Run this from inside the PASCHEN-1D folder, keep the 'studio' folder inside "
              f"it, set {S.ENV_VAR}=/path/to/PASCHEN-1D, or pass --solver PATH.")
        sys.exit(2)
    S.set_solver_root(found)
    return found


def _default_workspace() -> Path:
    from . import solver as S
    d = S.studio_dir() / "runs"
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d
    except OSError:
        d = Path.home() / "PASCHEN-1D-Studio" / "runs"
        d.mkdir(parents=True, exist_ok=True)
        return d


def _load(path: str):
    from .model import StudioModel
    p = Path(path)
    if not p.exists():
        print(f"✖ Model file not found: {p}")
        sys.exit(2)
    return StudioModel.load(p)


def _print_issues(issues) -> bool:
    sym = {"error": "✖", "warning": "!", "info": "·", "ok": "✔"}
    bad = False
    for i in issues:
        extra = f"   [{i.path}]" if i.path and i.level in ("error", "warning") else ""
        fix = f"   (fix: {i.fix_label})" if i.fix else ""
        print(f"  {sym.get(i.level, '·')} {i.message}{extra}{fix}")
        bad |= i.level == "error"
    return bad


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):      # never crash on a console that cannot show ✔ █ …
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    from . import APP_NAME, __version__
    p = argparse.ArgumentParser(prog="paschen-studio",
                                description=f"{APP_NAME} {__version__} – GUI and command line for PASCHEN-1D",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--solver", help="PASCHEN-1D folder (default: auto-detect)")
    sub = p.add_subparsers(dest="cmd")
    g = sub.add_parser("gui", help="start the graphical interface")
    g.add_argument("model", nargs="?")
    r = sub.add_parser("run", help="run a model")
    r.add_argument("model")
    r.add_argument("--workspace", "-w", help="folder for run outputs (default: studio/runs)")
    r.add_argument("--run-name", help="override the run (output folder) name")
    r.add_argument("--set", action="append", default=[], metavar="PATH=VALUE",
                   help="override a setting, e.g. --set waveform.V_peak=180 (repeatable)")
    r.add_argument("--test", action="store_true", help="quick test: 2 %% of the time steps, same dt")
    r.add_argument("--quiet", "-q", action="store_true", help="hide the solver log, show only the progress bar")
    s = sub.add_parser("sweep", help="run the sweep stored in a model (or define one)")
    s.add_argument("model")
    s.add_argument("--workspace", "-w")
    s.add_argument("--param", help="setting to sweep, e.g. waveform.V_peak")
    s.add_argument("--values", help="comma separated values, e.g. 140,160,180")
    s.add_argument("--range", nargs=3, metavar=("START", "END", "N"), help="linear range")
    s.add_argument("--log", action="store_true", help="logarithmic spacing for --range")
    s.add_argument("--quiet", "-q", action="store_true")
    c = sub.add_parser("check", help="validate a model")
    c.add_argument("model")
    sub.add_parser("cases", help="list case modules")
    n = sub.add_parser("new", help="create a model file from a case module")
    n.add_argument("case")
    n.add_argument("out")
    e = sub.add_parser("export-script", help="write a plain Python script that runs the model")
    e.add_argument("model")
    e.add_argument("out")
    rs = sub.add_parser("results", help="list run folders")
    rs.add_argument("folder", nargs="?")
    sub.add_parser("info", help="versions and paths")
    a = p.parse_args(argv)

    if a.cmd in (None, "gui"):
        from .gui.app import main as gui_main
        return gui_main(getattr(a, "model", None), a.solver)

    root = _setup_solver(a.solver)
    from . import advisor as A
    from . import solver as S

    if a.cmd == "info":
        import platform
        sv, sd = S.solver_version()
        print(f"{APP_NAME} {__version__}")
        print(f"PASCHEN-1D {sv} ({sd})  at  {root}")
        print(f"Python {sys.version.split()[0]} on {platform.platform()}")
        for mod in ("numpy", "scipy", "matplotlib", "numba", "tqdm", "PySide6"):
            try:
                m = __import__(mod)
                print(f"  {mod:<11} {getattr(m, '__version__', '?')}")
            except ImportError:
                print(f"  {mod:<11} NOT INSTALLED" + ("  (GUI unavailable: pip install PySide6)" if mod == "PySide6"
                                                     else ""))
        try:
            import numba
            print(f"  numba threads: {numba.config.NUMBA_NUM_THREADS}")
        except Exception:
            pass
        print(f"Default workspace: {_default_workspace()}")
        print(f"Electron tables: {len(S.electron_tables())} · ion pairs: "
              f"{len(S.ion_manifest().get('compatible_mobility_diffusion_pairs', []))}")
        return 0

    if a.cmd == "cases":
        for cinfo in S.list_cases():
            print(f"  {cinfo.module:<46} {cinfo.title}")
            print(f"  {'':<46} {cinfo.summary[:100]}")
        return 0

    if a.cmd == "new":
        from .model import new_model_from_case
        m = new_model_from_case(a.case)
        out = m.save(a.out)
        print(f"✔ wrote {out}")
        return 0

    if a.cmd == "export-script":
        m = _load(a.model)
        Path(a.out).write_text(m.to_python_script(), encoding="utf-8")
        print(f"✔ wrote {a.out}")
        return 0

    if a.cmd == "results":
        from .runs import discover
        folder = Path(a.folder) if a.folder else _default_workspace()
        infos = discover([folder])
        if not infos:
            print(f"No runs in {folder}")
        for i in infos:
            print(f"  {i.status:<11} {i.name:<50} {i.title}")
        return 0

    if a.cmd == "check":
        m = _load(a.model)
        print(f"Model: {m.display_title()}  (case {m.base_case}, {len(m.overrides)} changed settings)")
        return 1 if _print_issues(A.check_model(m, workspace=None)) else 0

    if a.cmd == "run":
        from .sweep import run_job_blocking
        from .units import parse_quantity
        m = _load(a.model)
        extra = {}
        for item in a.set:
            if "=" not in item:
                print(f"✖ --set expects PATH=VALUE, got {item!r}")
                return 2
            k, val = item.split("=", 1)
            k = k.strip()
            fi = m.schema.fields.get(k)
            if fi is None:
                print(f"✖ unknown setting {k!r}")
                return 2
            if fi.kind == "int":
                extra[k] = int(float(val))
            elif fi.kind in ("float", "optional_float"):
                extra[k] = parse_quantity(val)
            elif fi.kind == "bool":
                extra[k] = val.strip().lower() in ("1", "true", "yes", "on")
            else:
                extra[k] = val
        for k, v in extra.items():
            m.set(k, v)
        issues = A.check_model(m, workspace=None)
        if any(i.level == "error" for i in issues):
            print("Model check failed:")
            _print_issues(issues)
            return 1
        ws = Path(a.workspace) if a.workspace else _default_workspace()
        name = a.run_name or m.run_name
        run_extra = {}
        if a.test:
            v = m.values()
            Nt = int(v["numerics.Nt"])
            dt = float(v["run.T_total"]) / max(Nt - 1, 1)
            Nt2 = max(500, min(Nt, int(Nt * 0.02) + 1))
            run_extra = {"numerics.Nt": Nt2, "run.T_total": dt * (Nt2 - 1),
                         "output.save_every": max(1, (Nt2 - 1) // 200)}
            name = name + "_test"
        est = A.estimate(m)
        from .units import format_quantity, human_bytes, human_duration
        print(f"▶ {m.display_title()}  →  {ws / name}")
        print(f"  Nx = {est['Nx']}, Nt = {est['Nt']:,}, dt = {format_quantity(est['dt'], 's')}, "
              f"output ≈ {human_bytes(est['bytes_total'])}, estimated {human_duration(est['runtime_s'])}")
        print("  (Ctrl+C stops the run early and keeps the results)")
        return run_job_blocking(m, ws, name, extra=run_extra, label=m.display_title(), quiet=a.quiet)

    if a.cmd == "sweep":
        from .sweep import make_values, run_job_blocking, sweep_jobs
        from .units import parse_quantity
        m = _load(a.model)
        sw = dict(m.sweep or {})
        if a.param:
            sw["parameter"] = a.param
        if a.values:
            sw["values"] = [parse_quantity(x) for x in a.values.split(",") if x.strip()]
        if a.range:
            sw["values"] = make_values(parse_quantity(a.range[0]), parse_quantity(a.range[1]), int(a.range[2]),
                                       "log" if a.log else "linear")
        if not sw.get("parameter") or not sw.get("values"):
            print("✖ No sweep defined. Use --param and --values/--range, or define a sweep in the GUI.")
            return 2
        fi = m.schema.fields.get(sw["parameter"])
        if fi is None:
            print(f"✖ unknown setting {sw['parameter']!r}")
            return 2
        vals = [int(round(float(x))) if fi.kind == "int" else float(x) for x in sw["values"]]
        issues = A.check_model(m, workspace=None)
        if any(i.level == "error" for i in issues):
            _print_issues(issues)
            return 1
        ws = Path(a.workspace) if a.workspace else _default_workspace()
        from .model import unique_run_name
        jobs = sweep_jobs(m, sw["parameter"], vals, sw.get("prefix"))
        rc = 0
        for k, jd in enumerate(jobs, 1):
            name = unique_run_name(jd["run_name"], ws)
            print(f"\n[{k}/{len(jobs)}] {sw['parameter']} = {jd['sweep_info']['value']}  →  {name}")
            rc |= run_job_blocking(m, ws, name, extra=jd["extra"], label=jd["label"], sweep_info=jd["sweep_info"],
                                   quiet=True)
        print("\nSweep summary")
        from .runs import RunData, summary_metrics
        print(f"  {sw['parameter']:<24} {'peak I [A]':>14} {'min V_gap [V]':>14} {'final V_gap [V]':>16}")
        for jd in jobs:
            for d in sorted(ws.glob(jd["run_name"] + "*")):
                try:
                    met = summary_metrics(RunData.open(d))
                    print(f"  {jd['sweep_info']['value']!s:<24} {met.get('I_peak_A', float('nan')):>14.4g} "
                          f"{met.get('V_gap_min_V', float('nan')):>14.4g} {met.get('V_gap_final_V', float('nan')):>16.4g}")
                except Exception:
                    pass
                break
        return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
