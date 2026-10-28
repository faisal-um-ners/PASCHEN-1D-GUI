"""Parameter sweeps (shared by the GUI and the command line)."""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import numpy as np

from . import solver as S


def make_values(v0: float, v1: float, n: int, spacing: str = "linear") -> list[float]:
    if v0 is None or v1 is None:
        raise ValueError("start and end values are required")
    n = max(2, int(n))
    if spacing.startswith("log"):
        if v0 <= 0 or v1 <= 0:
            raise ValueError("logarithmic spacing needs positive start and end values")
        return [float(x) for x in np.logspace(math.log10(v0), math.log10(v1), n)]
    return [float(x) for x in np.linspace(v0, v1, n)]


def _fmt_val(v) -> str:
    if isinstance(v, int):
        return str(v)
    s = f"{v:.4g}".replace("+", "").replace(".", "p").replace("-", "m")
    return s


def sweep_jobs(model, parameter: str, values, prefix: str | None = None, sweep_id: str | None = None,
               label: str | None = None) -> list[dict]:
    """Return one job description per value: run name, extra overrides and sweep metadata."""
    sid = sweep_id or f"{_dt.datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"
    prefix = prefix or f"{model.run_name}_sweep"
    name = parameter.split(".")[-1]
    jobs = []
    for i, v in enumerate(values):
        run_name = f"{prefix}_{i + 1:02d}_{name}_{_fmt_val(v)}"
        jobs.append(dict(
            run_name=run_name,
            extra={parameter: v},
            label=f"{model.display_title()} · {name} = {v:.4g}" if isinstance(v, float) else
            f"{model.display_title()} · {name} = {v}",
            sweep_info=dict(id=sid, parameter=parameter, value=v, index=i, count=len(values),
                            label=label or f"{name} ({len(values)} values) · {model.display_title()}"),
        ))
    return jobs


def run_job_blocking(model, workspace: Path, run_name: str, extra: dict | None = None, label: str | None = None,
                     sweep_info: dict | None = None, quiet: bool = False) -> int:
    """Run one job through the worker in a subprocess, printing compact progress (CLI)."""
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    jobdir = workspace / ".studio_jobs"
    jobdir.mkdir(exist_ok=True)
    jf = jobdir / f"cli_{os.getpid()}_{int(time.time() * 1000)}.json"
    jf.write_text(json.dumps({
        "model": model.to_dict(), "workspace": str(workspace), "run_name": run_name,
        "solver_root": str(S.solver_root()), "extra_overrides": extra or {}, "label": label,
        "sweep_info": sweep_info, "model_dir": str(model.path.parent) if model.path else None,
        "extra_sys_path": [model.base_case_dir] if model.base_case_dir else [],
    }, default=str), encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(S.studio_dir()), str(S.solver_root())] +
                                        ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("MPLBACKEND", "Agg")
    proc = subprocess.Popen([sys.executable, "-u", "-m", "paschen_studio.worker", str(jf)], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env,
                            cwd=str(workspace), bufsize=1)
    from .units import human_duration
    from .worker import PREFIX
    last_draw = 0.0
    status = "failed"
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            if line.startswith(PREFIX):
                try:
                    ev = json.loads(line[len(PREFIX):])
                except json.JSONDecodeError:
                    continue
                e = ev.get("event")
                if e == "progress":
                    now = time.time()
                    if now - last_draw > 0.5 or ev.get("eta") == 0.0:
                        last_draw = now
                        tot = ev.get("total") or 1
                        frac = ev["n"] / tot
                        bar = "█" * int(30 * frac) + "░" * (30 - int(30 * frac))
                        eta = ev.get("eta")
                        sys.stdout.write(f"\r  {bar} {100 * frac:5.1f} %  {ev.get('rate', 0):8.0f} steps/s  "
                                         f"ETA {human_duration(eta) if eta is not None else '–':>10}   ")
                        sys.stdout.flush()
                elif e == "phase" and (not quiet or ev.get("phase") == "time-stepping"):
                    sys.stdout.write(f"\n  ▸ {ev.get('phase')}\n" if ev.get("phase") == "time-stepping" else
                                     f"  ▸ {ev.get('phase')}\n")
                elif e == "error":
                    sys.stdout.write(f"\n  ✖ {ev.get('kind')}: {ev.get('message')}\n")
                elif e == "done":
                    status = ev.get("status", "finished")
                    sys.stdout.write(f"\n  ✔ {status} in {human_duration(ev.get('elapsed'))}\n" if status in
                                     ("finished", "stopped") else f"\n  ✖ {status}\n")
            elif not quiet:
                sys.stdout.write("    " + line + "\n")
    except KeyboardInterrupt:
        (workspace / run_name / ".studio_control").write_text("stop", encoding="utf-8")
        sys.stdout.write("\n  ■ stop requested – the solver is writing its metadata…\n")
        proc.wait()
        status = "stopped"
    proc.wait()
    try:
        jf.unlink()
    except OSError:
        pass
    return 0 if status in ("finished", "stopped") else 1
