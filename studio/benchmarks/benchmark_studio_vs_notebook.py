"""Benchmark: PASCHEN-1D Studio (GUI worker) vs. the Jupyter-notebook workflow.

Both paths call the same solver function, ``run_simulation(cfg)``, on the same configuration:

* **notebook** - the code of ``run_paschen_1d.ipynb`` (load case, set fields on ``cfg``,
  ``run_simulation(cfg)``) executed in a Jupyter kernel (``nbclient``) or, if Jupyter is not
  installed, in a plain Python process (identical code, ``--notebook-runner python``).
* **studio**   - exactly what the GUI's Run button starts: ``python -m paschen_studio.worker job.json``
  (progress reporting, pause/stop control, studio files, summary metrics).

Measured for every run:

* ``loop_s``  - the solver's own time-loop timer (``Elapsed time`` printed by ``run_simulation``);
* ``total_s`` - end to end: for the notebook the execution time of the cell (kernel already running),
  for the studio the worker process from launch to exit (Python start, imports, run, summary);
* ``steps_per_s`` - macro time steps per second of the time loop.

Also compared: ``numerics.numba_parallel`` off/on, a cold start (empty Numba cache, includes JIT
compilation) and running several simulations at once (the studio's "Simultaneous runs").

Usage (from the PASCHEN-1D folder)::

    python studio/benchmarks/benchmark_studio_vs_notebook.py --out bench.json
    python studio/benchmarks/benchmark_studio_vs_notebook.py --report bench.json > report.md

The solver files are not modified; run folders, job files and Numba caches go to ``--work``.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve()
STUDIO = HERE.parents[1]
SOLVER = STUDIO.parent

# Benchmark cases: the shipped case modules with the simulated time shortened (dt and grid unchanged)
# so each run takes well under a minute.  `steps` = macro time steps.
CASES = {
    "ar_dc": dict(case="config_case_argon_dc_discharge", label="Argon DC glow (Nx 200, dt 10 ps)",
                  steps=100_000, save_every=800),
    "ar_photo": dict(case="config_case_argon_photoemission_discharge",
                     label="Argon photoemission (Nx 200, dt 8 ps, adaptive)", steps=80_000, save_every=1750),
    "n2_dbd": dict(case="config_case_nitrogen_pulsed_discharge", label="Nitrogen ns-pulse DBD (Nx 1000, dt 1 ps)",
                   steps=100_000, save_every=300),
    "d2_dbd": dict(case="config_case_deuterium_pulsed_discharge",
                   label="Deuterium ns-pulse DBD (Nx 1000, dt 1 ps, LXCat tables)", steps=100_000, save_every=300),
    "n2_fine": dict(case="config_case_nitrogen_pulsed_discharge", label="Nitrogen DBD, fine grid (Nx 8000, dt 0.1 ps)",
                    steps=20_000, save_every=1000, extra={"numerics.Nx": 8000}, dt_factor=0.1),
}

ELAPSED_RE = re.compile(r"Elapsed time:\s*([0-9.eE+-]+)\s*s")


SCALE = 1.0


def case_overrides(key: str, parallel: bool, run_name: str) -> dict:
    """Dotted-path overrides applied identically in both paths."""
    sys.path.insert(0, str(SOLVER))
    from config_loader import load_simulation_case
    c = CASES[key]
    cfg_cls, _ = load_simulation_case(c["case"])
    cfg = cfg_cls()
    nt0, T0 = int(cfg.numerics.Nt), float(cfg.run.T_total)
    dt = T0 / (nt0 - 1) * float(c.get("dt_factor", 1.0))
    nt = int(c["steps"] * SCALE) + 1
    ov = dict(c.get("extra", {}))
    ov.update({"numerics.Nt": nt, "run.T_total": dt * (nt - 1), "numerics.numba_parallel": bool(parallel),
               "output.save_every": int(c["save_every"]), "run.run_name": run_name})
    return ov


def _env(cache: Path, threads: int | None) -> dict:
    env = dict(os.environ)
    env["NUMBA_CACHE_DIR"] = str(cache / "numba")
    env["PYTHONPYCACHEPREFIX"] = str(cache / "pycache")
    env["MPLBACKEND"] = "Agg"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if threads:
        env["NUMBA_NUM_THREADS"] = str(threads)
    return env


# ---------------------------------------------------------------------------
def notebook_code(case: str, overrides: dict, workspace: Path) -> str:
    """The run cell of run_paschen_1d.ipynb with the benchmark overrides written out as a user would."""
    lines = [
        "import os, sys, time",
        f"os.chdir({str(workspace)!r})",
        f"sys.path.insert(0, {str(SOLVER)!r})",
        "_t0 = time.perf_counter()",
        "from config_loader import load_simulation_case",
        f"SimulationConfig, run_simulation = load_simulation_case({case!r})",
        "cfg = SimulationConfig()",
    ]
    for path, val in overrides.items():
        lines.append(f"cfg.{path} = {val!r}")
    lines += ["state = run_simulation(cfg)",
              "print('@@CELL@@', time.perf_counter() - _t0)"]
    return "\n".join(lines)


def run_notebook(case: str, overrides: dict, workspace: Path, cache: Path, threads, runner: str) -> dict:
    code = notebook_code(case, overrides, workspace)
    env = _env(cache, threads)
    t0 = time.perf_counter()
    if runner == "jupyter":
        import nbformat
        from nbclient import NotebookClient
        nb = nbformat.v4.new_notebook()
        nb.cells = [nbformat.v4.new_code_cell(code)]
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            client = NotebookClient(nb, timeout=3600, kernel_name="python3")
            client.execute()
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        out = "".join(o.get("text", "") for o in nb.cells[0].get("outputs", []) if o.get("output_type") == "stream")
    else:
        p = subprocess.run([sys.executable, "-u", "-c", code], capture_output=True, text=True, env=env,
                           encoding="utf-8", errors="replace")
        out = p.stdout + p.stderr
        if p.returncode:
            raise RuntimeError(out[-2000:])
    wall = time.perf_counter() - t0
    m = ELAPSED_RE.search(out)
    cell = re.search(r"@@CELL@@\s*([0-9.eE+-]+)", out)
    return {"loop_s": float(m.group(1)) if m else None, "total_s": float(cell.group(1)) if cell else wall,
            "process_s": wall}


def run_studio(case: str, overrides: dict, workspace: Path, cache: Path, threads) -> dict:
    run_name = overrides["run.run_name"]
    model = {"format": "paschen-studio-model/1", "title": run_name, "base_case": case,
             "overrides": {k: v for k, v in overrides.items() if k != "run.run_name"}}
    jobdir = workspace / ".studio_jobs"
    jobdir.mkdir(parents=True, exist_ok=True)
    jf = jobdir / f"{run_name}.json"
    jf.write_text(json.dumps({"model": model, "workspace": str(workspace), "run_name": run_name,
                              "solver_root": str(SOLVER), "extra_overrides": {}, "label": run_name}),
                  encoding="utf-8")
    env = _env(cache, threads)
    env["PYTHONPATH"] = os.pathsep.join([str(STUDIO), str(SOLVER)])
    t0 = time.perf_counter()
    p = subprocess.run([sys.executable, "-u", "-m", "paschen_studio.worker", str(jf)], capture_output=True,
                       text=True, env=env, cwd=str(workspace), encoding="utf-8", errors="replace")
    wall = time.perf_counter() - t0
    out = p.stdout + p.stderr
    if p.returncode:
        raise RuntimeError(out[-2000:])
    m = ELAPSED_RE.search(out)
    return {"loop_s": float(m.group(1)) if m else None, "total_s": wall, "process_s": wall}


def start_studio(case: str, overrides: dict, workspace: Path, cache: Path, threads):
    """Launch a worker without waiting (concurrency test)."""
    run_name = overrides["run.run_name"]
    model = {"format": "paschen-studio-model/1", "title": run_name, "base_case": case,
             "overrides": {k: v for k, v in overrides.items() if k != "run.run_name"}}
    jobdir = workspace / ".studio_jobs"
    jobdir.mkdir(parents=True, exist_ok=True)
    jf = jobdir / f"{run_name}.json"
    jf.write_text(json.dumps({"model": model, "workspace": str(workspace), "run_name": run_name,
                              "solver_root": str(SOLVER), "extra_overrides": {}, "label": run_name}),
                  encoding="utf-8")
    env = _env(cache, threads)
    env["PYTHONPATH"] = os.pathsep.join([str(STUDIO), str(SOLVER)])
    return subprocess.Popen([sys.executable, "-u", "-m", "paschen_studio.worker", str(jf)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, cwd=str(workspace))


# ---------------------------------------------------------------------------
def machine_info() -> dict:
    info = {"platform": platform.platform(), "machine": platform.machine(), "python": sys.version.split()[0],
            "cpus": os.cpu_count()}
    try:
        import numba
        import numpy
        info.update(numpy=numpy.__version__, numba=numba.__version__, numba_threads=numba.config.NUMBA_NUM_THREADS)
    except Exception:
        pass
    try:
        if sys.platform == "darwin":
            info["cpu"] = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                                         text=True).stdout.strip()
        elif Path("/proc/cpuinfo").exists():
            for ln in Path("/proc/cpuinfo").read_text().splitlines():
                if ln.lower().startswith(("model name", "cpu model")):
                    info["cpu"] = ln.split(":", 1)[1].strip()
                    break
    except Exception:
        pass
    return info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", default=",".join(CASES), help="comma-separated: " + ", ".join(CASES))
    ap.add_argument("--repeats", type=int, default=2, help="warm repeats per configuration")
    ap.add_argument("--no-parallel", action="store_true", help="skip numba_parallel=True runs")
    ap.add_argument("--parallel", choices=["both", "off", "on"], default="both", help="numba_parallel settings")
    ap.add_argument("--modes", default="notebook,studio", help="paths to run: notebook, studio")
    ap.add_argument("--append", action="store_true", help="add to an existing --out file (run in pieces)")
    ap.add_argument("--no-cold", action="store_true", help="skip the cold-start (JIT compile) runs")
    ap.add_argument("--concurrency", default="1,2,4", help="simultaneous studio runs to test ('' to skip)")
    ap.add_argument("--concurrency-case", default="ar_dc")
    ap.add_argument("--notebook-runner", choices=["auto", "jupyter", "python"], default="auto")
    ap.add_argument("--scale", type=float, default=1.0, help="multiply the number of time steps (quick tests)")
    ap.add_argument("--work", default=None, help="scratch folder (default: a temporary folder)")
    ap.add_argument("--out", default="benchmark_results.json")
    ap.add_argument("--report", metavar="RESULTS_JSON", help="print a Markdown report for a results file")
    a = ap.parse_args(argv)
    if a.report:
        print(make_report(json.loads(Path(a.report).read_text())))
        return 0

    global SCALE
    SCALE = a.scale
    runner = a.notebook_runner
    if runner == "auto":
        try:
            import ipykernel  # noqa: F401
            import nbclient  # noqa: F401
            runner = "jupyter"
        except ImportError:
            runner = "python"
    work = Path(a.work or tempfile.mkdtemp(prefix="p1d_bench_")).resolve()
    work.mkdir(parents=True, exist_ok=True)
    out_path = Path(a.out).resolve()
    if a.append and out_path.exists():
        res = json.loads(out_path.read_text())
    else:
        res = {"machine": machine_info(), "notebook_runner": runner, "cases": {}, "runs": [], "concurrency": [],
               "started": time.strftime("%Y-%m-%d %H:%M")}

    def save():
        out_path.write_text(json.dumps(res, indent=1))

    def log(msg):
        print(time.strftime("%H:%M:%S"), msg, flush=True)

    cases = [c for c in a.cases.split(",") if c]
    for key in cases:
        res["cases"][key] = {k: v for k, v in CASES[key].items()}
    parallels = {"both": [False, True], "off": [False], "on": [True]}[a.parallel]
    if a.no_parallel:
        parallels = [False]
    modes = [m for m in a.modes.split(",") if m]
    for key in cases:
        case = CASES[key]["case"]
        for mode in modes:
            cache = work / f"cache_{mode}"
            if not a.no_cold:                         # cold: empty Numba cache -> JIT compile in this run
                shutil.rmtree(cache, ignore_errors=True)
            ws = work / f"ws_{mode}"
            ws.mkdir(exist_ok=True)
            for par in parallels:
                if a.no_cold:                         # short unrecorded run: compile/load the kernels first
                    global SCALE
                    keep, SCALE = SCALE, max(0.005, SCALE * 0.01)
                    try:
                        ov = case_overrides(key, par, f"{key}_{mode}_warmup_{int(par)}")
                        (run_notebook(case, ov, ws, cache, None, runner) if mode == "notebook"
                         else run_studio(case, ov, ws, cache, None))
                    except Exception as exc:
                        log(f"   warm-up failed: {str(exc)[-200:]}")
                    finally:
                        SCALE = keep
                        shutil.rmtree(ws / f"{key}_{mode}_warmup_{int(par)}", ignore_errors=True)
                reps = a.repeats + (1 if (not a.no_cold and not par) else 0)
                for r in range(reps):
                    cold = (not a.no_cold and not par and r == 0)
                    name = f"{key}_{mode}_{'par' if par else 'ser'}_{r}"
                    ov = case_overrides(key, par, name)
                    log(f"{key:9s} {mode:8s} parallel={par!s:5s} {'cold' if cold else 'warm'} …")
                    try:
                        if mode == "notebook":
                            m = run_notebook(case, ov, ws, cache, None, runner)
                        else:
                            m = run_studio(case, ov, ws, cache, None)
                    except Exception as exc:  # keep going, record the failure
                        log(f"   failed: {str(exc)[-300:]}")
                        res["runs"].append({"case": key, "mode": mode, "parallel": par, "cold": cold,
                                            "error": str(exc)[-500:]})
                        save()
                        continue
                    m.update(case=key, mode=mode, parallel=par, cold=cold, steps=int(ov["numerics.Nt"]) - 1)
                    if m.get("loop_s"):
                        m["steps_per_s"] = m["steps"] / m["loop_s"]
                    res["runs"].append(m)
                    log(f"   loop {m.get('loop_s') or float('nan'):.2f} s   total {m['total_s']:.2f} s")
                    save()
                    shutil.rmtree(ws / name, ignore_errors=True)

    # several runs at once (studio "Simultaneous runs") vs one after the other
    levels = [int(x) for x in a.concurrency.split(",") if x.strip()]
    if levels:
        key = a.concurrency_case
        case = CASES[key]["case"]
        cache = work / "cache_studio"
        ws = work / "ws_conc"
        ws.mkdir(exist_ok=True)
        n_jobs = max(levels)
        for level in levels:
            log(f"concurrency {level}: {n_jobs} × {key}")
            t0 = time.perf_counter()
            pending = list(range(n_jobs))
            active = []
            while pending or active:
                while pending and len(active) < level:
                    i = pending.pop(0)
                    ov = case_overrides(key, False, f"conc{level}_{i}")
                    active.append(start_studio(case, ov, ws, cache, None))
                for p in list(active):
                    if p.poll() is not None:
                        active.remove(p)
                time.sleep(0.2)
            wall = time.perf_counter() - t0
            res["concurrency"].append({"case": key, "level": level, "jobs": n_jobs, "wall_s": wall,
                                       "per_run_s": wall / n_jobs})
            log(f"   {wall:.1f} s for {n_jobs} runs")
            save()
            shutil.rmtree(ws, ignore_errors=True)
            ws.mkdir(exist_ok=True)
    res["finished"] = time.strftime("%Y-%m-%d %H:%M")
    save()
    log(f"results: {out_path}")
    return 0


# ---------------------------------------------------------------------------
def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def make_report(res: dict) -> str:
    m = res["machine"]
    L = []
    L.append("| Case | Path | numba_parallel | Time loop [s] | End to end [s] | Steps/s |")
    L.append("|---|---|---|---:|---:|---:|")
    for key, c in res["cases"].items():
        for par in (False, True):
            for mode in ("notebook", "studio"):
                rr = [r for r in res["runs"] if r.get("case") == key and r.get("mode") == mode
                      and r.get("parallel") == par and not r.get("cold") and "error" not in r]
                if not rr:
                    continue
                L.append(f"| {c['label']} | {mode} | {'on' if par else 'off'} | {_mean(r['loop_s'] for r in rr):.2f} | "
                         f"{_mean(r['total_s'] for r in rr):.2f} | {_mean(r.get('steps_per_s') for r in rr):,.0f} |")
    L.append("")
    L.append(f"Machine: {m.get('cpu', m.get('machine'))}, {m.get('cpus')} CPUs, {m.get('platform')}, "
             f"Python {m.get('python')}, NumPy {m.get('numpy')}, Numba {m.get('numba')}. "
             f"Notebook runner: {res.get('notebook_runner')}.")
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
