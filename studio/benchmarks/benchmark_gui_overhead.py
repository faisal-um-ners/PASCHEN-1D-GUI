"""Does the GUI slow a simulation down?  Runs a model from the real Studio window (Simulate page with the
live monitor redrawing) and then the same model as a bare worker process, alternately.

Usage (from the PASCHEN-1D folder):  python studio/benchmarks/benchmark_gui_overhead.py WORKDIR [case] [scale]
"""
import json
import os
import sys
import time
from pathlib import Path

WORK = Path(sys.argv[1] if len(sys.argv) > 1 else "gui_overhead_work").resolve()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["NUMBA_CACHE_DIR"] = str(WORK / "cache" / "numba")
os.environ["PYTHONPYCACHEPREFIX"] = str(WORK / "cache" / "pycache")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import benchmark_studio_vs_notebook as B  # noqa: E402
from PySide6.QtCore import QCoreApplication  # noqa: E402

QCoreApplication.setOrganizationName("PASCHEN-1D-bench")
from paschen_studio.gui.app import setup_application  # noqa: E402

app = setup_application(theme_name="light")
from PySide6.QtWidgets import QApplication  # noqa: E402
from paschen_studio.gui.main_window import MainWindow  # noqa: E402
from paschen_studio.model import StudioModel  # noqa: E402

key = sys.argv[2] if len(sys.argv) > 2 else "ar_dc"
B.SCALE = float(sys.argv[3]) if len(sys.argv) > 3 else 0.3
WORK.mkdir(parents=True, exist_ok=True)
w = MainWindow()
w.resize(1470, 900)
w.show()
w.workspace = WORK
res = []
for rep in range(3):                     # the first pair includes JIT compilation
    ov = B.case_overrides(key, False, f"gui_{key}_{rep}")
    m = StudioModel(B.CASES[key]["case"])
    for k, v in ov.items():
        m.set(k, v)
    w.set_model(m, dirty=False)
    t0 = time.perf_counter()
    job = w.run_current()
    while not job.done:
        QApplication.processEvents()
        time.sleep(0.02)
    gui_s = time.perf_counter() - t0
    ov["run.run_name"] = f"alone_{key}_{rep}"
    alone = B.run_studio(B.CASES[key]["case"], ov, WORK, WORK / "cache", None)
    res.append({"gui_total_s": gui_s, "alone_total_s": alone["total_s"], "alone_loop_s": alone["loop_s"]})
    print(res[-1], flush=True)
(WORK / "gui_overhead.json").write_text(json.dumps(res, indent=1))
