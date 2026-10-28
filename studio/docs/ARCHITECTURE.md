# How PASCHEN-1D Studio works

The studio is a separate layer in `studio/`. It must never change PASCHEN-1D, so everything it knows about
the solver is discovered at run time and every simulation goes through the solver's public API.

```
                 ┌───────────────────────────── studio/ ─────────────────────────────┐
  PySide6 GUI ───┤ gui/  (pages, forms, previews, plots, run queue)                   │
  CLI ───────────┤ __main__.py                                                        │
                 │   │                                                                │
                 │   ├─ solver.py   locate PASCHEN-1D, list cases, read the schema    │
                 │   ├─ schema.py   labels, units, sections, relevance rules           │
                 │   ├─ model.py    base case + overrides  ⇄  *.p1d.json              │
                 │   ├─ advisor.py  validation, estimates, fixes, Paschen estimate     │
                 │   ├─ runs.py     read run folders (finished, stopped, running)      │
                 │   └─ worker.py   one simulation per process (progress + control)    │
                 └───────────┬────────────────────────────────────────────────────────┘
                             │ imports (read-only)
  PASCHEN-1D:  config_loader.load_simulation_case · validation.validate_simulation_config ·
               paschen_1d.run_simulation · physics.* builders · diagnostics_io · data_paths ·
               ion_transport · config*.py dataclasses + comments
```

## Reading the configuration

`solver.load_schema(case)` imports the case module through `config_loader.load_config_module`, walks the
`SimulationConfig` dataclass tree (`dataclasses.fields` + `typing.get_type_hints`) and parses the module source
with `ast` to collect the comment above every field and the `# %% [markdown]` guide above every class.
Field kinds come from the type annotations (`Literal[...]` → choice, `bool` → switch, `float` → quantity,
`tuple[Literal, ...]` → multi-choice …). A future solver release that adds settings is therefore picked up
automatically; `schema.py` only adds presentation (labels, units, sections, relevance).

## Building a configuration

`StudioModel.build_config()` does exactly what the run notebook does:

```python
SimulationConfig, run_simulation = load_simulation_case(base_case)
cfg = SimulationConfig()
cfg.<group>.<field> = value        # for every override
```

## Running

`worker.py` is started as `python -m paschen_studio.worker job.json` (by the GUI with `QProcess`, by the CLI
with `subprocess`). It changes into the workspace, builds `cfg`, writes `studio_run.json`, and calls
`run_simulation(cfg)`.

Progress and control use the solver's own loop: `paschen_1d.run_simulation` iterates
`tqdm(range(Nt - 1), …)`, where `tqdm` is a module-level name. Before calling it, the worker assigns its own
progress iterator to `paschen_1d.tqdm` (and to `emission.tqdm` for the photoemission precompute). This is an
in-memory assignment in the worker process; no file is changed. The iterator

* emits `@@STUDIO@@ {json}` progress lines (steps, rate over a sliding window, ETA);
* polls `<run>/.studio_control` every 0.25 s: `pause` blocks between steps, `stop` ends the iteration so
  the solver finishes normally and writes `run_metadata.json`, `abort` raises `KeyboardInterrupt`.

## Live view

The solver allocates all outputs as fixed-size memory-mapped files before the loop. The GUI opens them
read-only from its own process and reads only the part already written (step index from the progress
events, snapshot index = steps // save_every). Long histories are decimated with a min/max envelope so
spikes stay visible.

## Keeping the solver folder pristine

Importing modules normally writes `__pycache__/` next to the sources and Numba's `cache=True` kernels next to
`numerics_jit.py`. The studio sets `sys.pycache_prefix`, `PYTHONPYCACHEPREFIX` and `NUMBA_CACHE_DIR` to
`studio/.cache` (or `~/.cache/paschen-studio`) before importing the solver, in the GUI, the CLI and every
worker. Run outputs go to the workspace (`studio/runs` by default).

## Files written by a run

```
<workspace>/<run_name>/
    *_mm.dat, run_metadata.json, surface_emission_charge_stats.json   ← written by PASCHEN-1D
    studio_run.json            status, grid, full configuration, summary metrics, sweep info
    studio_model.p1d.json      the exact model used (reload with "Open model in builder")
    .studio_control            run / pause / stop / abort
```

Run folders created with the notebooks are listed and analysed too (they simply lack the studio files).

## Tests

```bash
python -m pytest studio/tests -q
```

The tests load every case schema, round-trip models, check unit parsing, run the advisor on all cases,
execute a short simulation through the worker (including pause/stop), exercise the CLI and build the main
window off-screen.
