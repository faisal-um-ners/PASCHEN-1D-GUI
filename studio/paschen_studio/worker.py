"""Run one PASCHEN-1D simulation in its own process and report progress.

Usage (the GUI and the CLI both do this for you)::

    python -m paschen_studio.worker job.json

The worker:

1. builds the configuration from the job's model (base case + overrides);
2. calls the solver's public ``run_simulation(cfg)`` inside the run workspace;
3. reports progress as JSON lines prefixed with ``@@STUDIO@@`` on stdout;
4. honours pause / stop / abort requests written to ``<run>/.studio_control``.

Progress and control are obtained by handing the solver's time loop a
progress iterator in place of ``tqdm`` (attribute assignment on the imported
module at run time).  No PASCHEN-1D file is changed.  "Stop" ends the time loop
early so the solver still writes ``run_metadata.json`` for the steps computed.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import time
import traceback
from pathlib import Path

PREFIX = "@@STUDIO@@"


def emit(event: str, **data) -> None:
    data["event"] = event
    data["wall"] = time.time()
    sys.stdout.write(PREFIX + " " + json.dumps(data, default=str) + "\n")
    sys.stdout.flush()


class _Control:
    """Polls the control file written by the GUI (cheap: one stat per 0.25 s)."""

    def __init__(self, path: Path):
        self.path = path
        self._mtime = None
        self.state = "run"
        self.last_check = 0.0

    def poll(self, force: bool = False) -> str:
        now = time.monotonic()
        if not force and now - self.last_check < 0.25:
            return self.state
        self.last_check = now
        try:
            st = self.path.stat()
        except FileNotFoundError:
            return self.state
        if st.st_mtime != self._mtime:
            self._mtime = st.st_mtime
            try:
                self.state = self.path.read_text(encoding="utf-8").strip() or "run"
            except OSError:
                pass
        return self.state


class _Abort(KeyboardInterrupt):
    pass


class StudioRun:
    def __init__(self, job: dict):
        self.job = job
        self.control: _Control | None = None
        self.status_path: Path | None = None
        self.status: dict = {}
        self.steps_done = 0
        self.total = 0
        self.stopped_early = False
        self._last_status_write = 0.0

    # -- progress iterator handed to the solver in place of tqdm ---------------
    def make_progress(self):
        run = self

        class StudioProgress:
            def __init__(self, iterable=None, total=None, desc="", **kwargs):
                self.iterable = iterable
                self.desc = desc or ""
                if total is None and iterable is not None:
                    try:
                        total = len(iterable)
                    except TypeError:
                        total = None
                self.total = total
                self.n = 0

            def __iter__(self):
                main = self.desc.lower().startswith("time stepping")
                emit("phase", phase="time-stepping" if main else self.desc, total=self.total)
                if main:
                    run.total = int(self.total or 0)
                    run.set_status(status="running", phase="time-stepping", total=run.total)
                t0 = time.perf_counter()
                last = t0
                window = []                         # recent (time, n) samples for a steady rate/ETA
                for item in self.iterable:
                    yield item
                    self.n += 1
                    if main:
                        run.steps_done = self.n
                    now = time.perf_counter()
                    if now - last >= 0.25:
                        last = now
                        if main:
                            el = now - t0
                            window.append((now, self.n))
                            while len(window) > 2 and now - window[0][0] > 8.0:
                                window.pop(0)
                            dt_w = now - window[0][0]
                            rate = (self.n - window[0][1]) / dt_w if dt_w > 0.2 else (self.n / el if el > 0 else 0.0)
                            eta = (self.total - self.n) / rate if (rate > 0 and self.total and el > 1.5) else None
                            emit("progress", n=self.n, total=self.total, elapsed=el, rate=rate, eta=eta)
                            run.maybe_write_status(n=self.n, elapsed=el, rate=rate)
                            state = run.control.poll() if run.control else "run"
                            if state == "pause":
                                state = run.wait_while_paused()
                                last = time.perf_counter()
                            if state == "stop":
                                run.stopped_early = True
                                emit("stopping", n=self.n)
                                return
                            if state == "abort":
                                raise _Abort()
                        else:
                            emit("subprogress", phase=self.desc, n=self.n, total=self.total)
                if main:
                    el = time.perf_counter() - t0
                    emit("progress", n=self.n, total=self.total, elapsed=el,
                         rate=self.n / el if el > 0 else 0.0, eta=0.0)

            # tqdm compatibility no-ops
            def update(self, n=1):
                self.n += n

            def close(self):
                pass

            def set_description(self, *a, **k):
                pass

            def set_postfix(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return StudioProgress

    def wait_while_paused(self) -> str:
        emit("paused", n=self.steps_done)
        self.set_status(status="paused")
        t_pause = time.monotonic()
        while True:
            time.sleep(0.2)
            state = self.control.poll(force=True)
            if state != "pause":
                emit("resumed", n=self.steps_done, paused_for=time.monotonic() - t_pause)
                self.set_status(status="running")
                return state

    # -- status sidecar -------------------------------------------------------
    def set_status(self, **kw):
        if self.status_path is None:
            return
        from .runs import write_json_atomic
        self.status.update(kw)
        self.status["steps_done"] = self.steps_done
        self.status["updated"] = _dt.datetime.now().isoformat(timespec="seconds")
        try:
            write_json_atomic(self.status_path, self.status)
        except OSError:
            pass

    def maybe_write_status(self, **kw):
        now = time.monotonic()
        if now - self._last_status_write > 2.0:
            self._last_status_write = now
            self.set_status(**kw)

    # -- main -----------------------------------------------------------------
    def execute(self) -> int:
        job = self.job
        root = job.get("solver_root")
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from . import solver as S
        from .model import StudioModel, config_to_dict
        from .runs import CONTROL_FILE, MODEL_SNAPSHOT, STATUS_FILE

        S.set_solver_root(root or S.find_solver_root())
        for d in job.get("extra_sys_path", []) or []:
            S.add_case_dir(d)
        model = StudioModel.from_dict(job["model"])
        model_dir = job.get("model_dir")
        extra = dict(job.get("extra_overrides") or {})
        run_name = job.get("run_name") or model.run_name
        extra["run.run_name"] = run_name

        workspace = Path(job["workspace"]).expanduser().resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        os.chdir(workspace)

        cfg = model.build_config(extra)
        # Relative waveform tables are resolved like the notebook would (model folder, solver folder).
        if str(cfg.waveform.waveform_type) in ("table", "tabulated", "measured_table"):
            tp = Path(str(cfg.waveform.table_path)).expanduser()
            if not tp.is_absolute():
                for base in [model_dir, str(S.solver_root()), str(workspace)]:
                    if base and (Path(base) / tp).is_file():
                        cfg.waveform.table_path = str((Path(base) / tp).resolve())
                        break

        run_dir = workspace / run_name
        run_dir.mkdir(parents=True, exist_ok=True)
        self.status_path = run_dir / STATUS_FILE
        ctl = run_dir / CONTROL_FILE
        ctl.write_text("run", encoding="utf-8")
        self.control = _Control(ctl)
        snap = model.copy()
        for k, v in extra.items():
            snap.overrides[k] = v
        try:
            snap.save(run_dir / MODEL_SNAPSHOT)
        except OSError:
            pass

        from . import __version__
        flat = config_to_dict(cfg)
        Nt, Nx = int(cfg.numerics.Nt), int(cfg.numerics.Nx)
        self.status = {
            "studio_version": __version__,
            "solver_version": S.solver_version()[0],
            "status": "starting",
            "label": job.get("label") or model.display_title(),
            "base_case": model.base_case,
            "model_title": model.display_title(),
            "model_path": str(model.path) if model.path else None,
            "sweep": job.get("sweep_info"),
            "pid": os.getpid(),
            "started": _dt.datetime.now().isoformat(timespec="seconds"),
            "grid": {"Nt": Nt, "Nx": Nx, "T_total": float(cfg.run.T_total), "L": float(cfg.geometry.L),
                     "A": float(cfg.geometry.A), "save_every": int(cfg.output.save_every),
                     "log_intermediate": bool(cfg.output.log_intermediate)},
            "config": flat,
            "overrides": {k: v for k, v in snap.to_dict()["overrides"].items()},
            "python": sys.version.split()[0],
        }
        self.set_status()
        emit("start", run_dir=str(run_dir), run_name=run_name, Nt=Nt, Nx=Nx, T_total=float(cfg.run.T_total),
             save_every=int(cfg.output.save_every), pid=os.getpid())

        os.environ.setdefault("MPLBACKEND", "Agg")
        t_start = time.perf_counter()
        try:
            emit("phase", phase="importing solver")
            import paschen_1d
            progress_cls = self.make_progress()
            paschen_1d.tqdm = progress_cls          # time loop progress + control
            try:
                import emission as _emission
                _emission.tqdm = progress_cls       # photoemission pulse precompute
            except Exception:
                pass
            from config_loader import load_simulation_case
            _, run_simulation = load_simulation_case(model.base_case)
            emit("phase", phase="validating")
            self.set_status(status="running", phase="setup")
            emit("phase", phase="setup (tables, emission model, JIT compilation)")
            run_simulation(cfg)
        except _Abort:
            self.set_status(status="aborted", finished=_dt.datetime.now().isoformat(timespec="seconds"),
                            elapsed=time.perf_counter() - t_start)
            emit("done", status="aborted", steps_done=self.steps_done)
            return 3
        except KeyboardInterrupt:
            self.set_status(status="aborted", elapsed=time.perf_counter() - t_start)
            emit("done", status="aborted", steps_done=self.steps_done)
            return 3
        except BaseException as exc:  # noqa: BLE001 - report everything to the GUI
            tb = traceback.format_exc()
            sys.stdout.write(tb)
            self.set_status(status="failed", error=str(exc), traceback=tb,
                            finished=_dt.datetime.now().isoformat(timespec="seconds"),
                            elapsed=time.perf_counter() - t_start)
            emit("error", message=str(exc), kind=type(exc).__name__, traceback=tb)
            emit("done", status="failed", steps_done=self.steps_done)
            return 1

        elapsed = time.perf_counter() - t_start
        status = "stopped" if self.stopped_early else "finished"
        if not self.stopped_early:
            self.steps_done = Nt - 1
        summary = {}
        try:
            from .runs import RunData, summary_metrics
            rd = RunData.open(run_dir, steps_done=self.steps_done)
            summary = summary_metrics(rd)
            rd.close()
        except Exception as exc:  # pragma: no cover
            summary = {"error": str(exc)}
        self.set_status(status=status, stopped_early=self.stopped_early,
                        finished=_dt.datetime.now().isoformat(timespec="seconds"), elapsed=elapsed,
                        rate=(self.steps_done / elapsed if elapsed > 0 else None), summary=summary)
        emit("done", status=status, steps_done=self.steps_done, elapsed=elapsed, summary=summary)
        return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python -m paschen_studio.worker job.json")
        return 2
    job = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    if sys.stdout is None:            # pythonw without redirected handles
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = sys.stdout
    try:
        sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
    except Exception:
        pass
    return StudioRun(job).execute()


if __name__ == "__main__":
    sys.exit(main())
