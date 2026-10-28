"""Run queue: each simulation is a separate worker process (QProcess)."""
from __future__ import annotations

import collections
import itertools
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from .. import solver as S
from ..runs import CONTROL_FILE
from ..worker import PREFIX

_ids = itertools.count(1)


@dataclass
class Job:
    id: int
    label: str
    model_dict: dict
    run_name: str
    workspace: Path
    extra: dict = field(default_factory=dict)
    sweep_info: dict | None = None
    model_dir: str | None = None
    status: str = "queued"              # queued starting running paused stopping finished stopped failed aborted
    phase: str = ""
    n: int = 0
    total: int = 0
    rate: float = 0.0
    eta: float | None = None
    elapsed: float = 0.0
    started: float | None = None
    finished: float | None = None
    error: str = ""
    summary: dict = field(default_factory=dict)
    grid: dict = field(default_factory=dict)
    log: collections.deque = field(default_factory=lambda: collections.deque(maxlen=4000))
    proc: QProcess | None = None
    sub: str = ""
    jobfile: Path | None = None

    @property
    def run_dir(self) -> Path:
        return self.workspace / self.run_name

    @property
    def active(self) -> bool:
        return self.status in ("starting", "running", "paused", "stopping")

    @property
    def done(self) -> bool:
        return self.status in ("finished", "stopped", "failed", "aborted")

    @property
    def fraction(self) -> float:
        return (self.n / self.total) if self.total else 0.0

    def t_sim(self) -> float:
        g = self.grid
        if not g:
            return 0.0
        return self.n * float(g.get("T_total", 0)) / max(int(g.get("Nt", 2)) - 1, 1)


class JobManager(QObject):
    added = Signal(object)
    changed = Signal(object)
    logged = Signal(object, str)
    finished = Signal(object)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.jobs: list[Job] = []
        self._buf: dict[int, str] = {}
        self._kill_timers = {}
        self._last_event: dict[int, float] = {}
        # Fallback: if a worker's stdout is not delivered (e.g. unusual Windows set-ups),
        # follow its progress through the studio_run.json status file instead.
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._poll_status)
        self._poll.start(2000)

    # -- queue ------------------------------------------------------------------
    @property
    def max_concurrent(self) -> int:
        try:
            return max(1, int(self.settings.value("max_concurrent", 1)))
        except (TypeError, ValueError):
            return 1

    def enqueue(self, model, workspace: Path, run_name: str | None = None, extra: dict | None = None,
                label: str | None = None, sweep_info: dict | None = None) -> Job:
        d = model.to_dict()
        job = Job(id=next(_ids), label=label or model.display_title(), model_dict=d,
                  run_name=run_name or model.run_name, workspace=Path(workspace), extra=dict(extra or {}),
                  sweep_info=sweep_info, model_dir=str(model.path.parent) if model.path else None)
        self.jobs.append(job)
        self.added.emit(job)
        self._pump()
        return job

    def running(self) -> list[Job]:
        return [j for j in self.jobs if j.active]

    def _pump(self):
        while len(self.running()) < self.max_concurrent:
            nxt = next((j for j in self.jobs if j.status == "queued"), None)
            if nxt is None:
                return
            self._start(nxt)

    def _start(self, job: Job):
        job.workspace.mkdir(parents=True, exist_ok=True)
        jobdir = job.workspace / ".studio_jobs"
        jobdir.mkdir(exist_ok=True)
        jf = jobdir / f"job_{os.getpid()}_{job.id}_{int(time.time())}.json"
        payload = {"model": job.model_dict, "workspace": str(job.workspace), "run_name": job.run_name,
                   "solver_root": str(S.solver_root()), "extra_overrides": job.extra, "label": job.label,
                   "sweep_info": job.sweep_info, "model_dir": job.model_dir,
                   "extra_sys_path": [job.model_dict.get("base_case_dir")] if job.model_dict.get("base_case_dir") else []}
        jf.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
        job.jobfile = jf
        p = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        paths = [str(S.studio_dir()), str(S.solver_root())]
        old = env.value("PYTHONPATH", "")
        env.insert("PYTHONPATH", os.pathsep.join(paths + ([old] if old else [])))
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("MPLBACKEND", "Agg")
        p.setProcessEnvironment(env)
        p.setWorkingDirectory(str(job.workspace))
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.readyReadStandardOutput.connect(lambda j=job: self._read(j))
        p.finished.connect(lambda code, st, j=job: self._done(j, code))
        p.errorOccurred.connect(lambda err, j=job: self._error(j, err))
        job.proc = p
        job.status = "starting"
        job.phase = "starting Python"
        job.started = time.time()
        self._buf[job.id] = ""
        p.start(sys.executable, ["-u", "-m", "paschen_studio.worker", str(jf)])
        self.changed.emit(job)

    def _read(self, job: Job):
        p = job.proc
        if p is None:
            return
        data = bytes(p.readAllStandardOutput()).decode("utf-8", errors="replace")
        buf = self._buf.get(job.id, "") + data.replace("\r\n", "\n").replace("\r", "\n")
        lines = buf.split("\n")
        self._buf[job.id] = lines.pop()
        changed = False
        for ln in lines:
            if ln.startswith(PREFIX):
                try:
                    ev = json.loads(ln[len(PREFIX):].strip())
                except json.JSONDecodeError:
                    continue
                changed |= self._event(job, ev)
            elif ln.strip():
                job.log.append(ln)
                self.logged.emit(job, ln)
        if changed:
            self.changed.emit(job)

    def _poll_status(self):
        from ..runs import read_json
        now = time.time()
        for j in self.running():
            if now - self._last_event.get(j.id, j.started or now) < 4.0:
                continue
            st = read_json(j.run_dir / "studio_run.json")
            if not st:
                continue
            n = int(st.get("steps_done") or 0)
            if n > j.n:
                j.n = n
                j.total = int(st.get("total") or (st.get("grid") or {}).get("Nt", 2) - 1)
                j.grid = j.grid or dict(st.get("grid") or {})
                if st.get("rate"):
                    j.rate = float(st["rate"])
                    j.eta = (j.total - j.n) / j.rate if j.rate > 0 else None
                if j.status == "starting":
                    j.status = "running"
                self.changed.emit(j)

    def _event(self, job: Job, ev: dict) -> bool:
        self._last_event[job.id] = time.time()
        e = ev.get("event")
        if e == "start":
            job.grid = {"Nt": ev.get("Nt"), "Nx": ev.get("Nx"), "T_total": ev.get("T_total"),
                        "save_every": ev.get("save_every")}
            job.total = int(ev.get("Nt", 1)) - 1
            job.status = "running"
        elif e == "phase":
            ph = ev.get("phase", "")
            job.phase = ph
            if ph == "time-stepping":
                job.phase = "time stepping"
                job.total = int(ev.get("total") or job.total)
            self.logged.emit(job, f"▸ {job.phase}")
        elif e == "subprogress":
            tot = ev.get("total") or 0
            job.sub = f"{ev.get('phase', '')}: {ev.get('n', 0)}/{tot}"
        elif e == "progress":
            job.n = int(ev.get("n", 0))
            job.total = int(ev.get("total") or job.total)
            job.rate = float(ev.get("rate") or 0)
            job.eta = ev.get("eta")
            job.elapsed = float(ev.get("elapsed") or 0)
            job.sub = ""
            if job.status not in ("paused", "stopping"):
                job.status = "running"
        elif e == "paused":
            job.status = "paused"
            self.logged.emit(job, "⏸ paused")
        elif e == "resumed":
            job.status = "running"
            self.logged.emit(job, "▶ resumed")
        elif e == "stopping":
            job.status = "stopping"
            job.phase = "writing metadata"
            self.logged.emit(job, "■ stopping – the solver is finishing up and writing run_metadata.json")
        elif e == "error":
            job.error = ev.get("message", "")
            self.logged.emit(job, f"✖ {ev.get('kind', 'Error')}: {job.error}")
        elif e == "done":
            job.status = ev.get("status", "finished")
            job.summary = ev.get("summary") or {}
            if ev.get("steps_done") is not None:
                job.n = int(ev["steps_done"])
            if ev.get("elapsed"):
                job.elapsed = float(ev["elapsed"])
            self._calibrate(job)
        return True

    def _calibrate(self, job: Job):
        if job.status != "finished" or not job.elapsed or not job.grid:
            return
        try:
            steps = int(job.grid["Nt"]) - 1
            if steps < 2000 or job.elapsed < 5:
                return
            coeff = steps / job.elapsed * max(int(job.grid["Nx"]), 50)
            old = self.settings.value("rate_coeff", None)
            new = coeff if old in (None, "") else 0.5 * float(old) + 0.5 * coeff
            self.settings.setValue("rate_coeff", new)
        except Exception:
            pass

    def _done(self, job: Job, code: int):
        self._read(job)
        if not job.done:
            job.status = "finished" if code == 0 else ("aborted" if job.status in ("stopping",) else "failed")
            if code != 0 and not job.error:
                job.error = f"worker exited with code {code}"
        job.finished = time.time()
        try:
            if job.jobfile is not None:
                job.jobfile.unlink()
        except OSError:
            pass
        t = self._kill_timers.pop(job.id, None)
        if t:
            t.stop()
        self.changed.emit(job)
        self.finished.emit(job)
        job.proc = None
        self._pump()

    def _error(self, job: Job, err):
        if err == QProcess.FailedToStart:
            job.status = "failed"
            job.error = "Could not start the Python worker process."
            self.logged.emit(job, f"✖ {job.error}")
            self.changed.emit(job)
            self.finished.emit(job)
            self._pump()

    # -- control ------------------------------------------------------------------
    def _control(self, job: Job, word: str):
        try:
            (job.run_dir / CONTROL_FILE).write_text(word, encoding="utf-8")
        except OSError:
            pass

    def pause(self, job: Job):
        if job.status == "running":
            self._control(job, "pause")

    def resume(self, job: Job):
        if job.status == "paused":
            self._control(job, "run")

    def stop(self, job: Job):
        """Finish early but keep results (the solver writes its metadata)."""
        if job.status == "queued":
            job.status = "aborted"
            self.changed.emit(job)
            return
        if job.active:
            self._control(job, "stop")
            job.status = "stopping"
            self.changed.emit(job)

    def abort(self, job: Job):
        if job.status == "queued":
            job.status = "aborted"
            self.changed.emit(job)
            return
        if job.active:
            self._control(job, "abort")
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(lambda j=job: j.proc.kill() if j.proc is not None else None)
            t.start(4000)
            self._kill_timers[job.id] = t

    def remove(self, job: Job):
        if job.active:
            return
        self.jobs = [j for j in self.jobs if j is not job]

    def clear_done(self):
        self.jobs = [j for j in self.jobs if not j.done]

    def shutdown(self, wait_ms: int = 8000):
        """Stop every running job gracefully (results so far are kept)."""
        for j in self.running():
            self._control(j, "stop")
            if j.status == "paused":
                self._control(j, "stop")
        deadline = time.time() + wait_ms / 1000.0
        for j in list(self.running()):
            if j.proc is not None:
                left = max(0, int((deadline - time.time()) * 1000))
                if not j.proc.waitForFinished(left):
                    j.proc.kill()
                    j.proc.waitForFinished(1000)
