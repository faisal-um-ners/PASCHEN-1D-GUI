"""Figures for PERFORMANCE.md from a benchmark results file."""
import json
import statistics as st
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

res = json.loads(Path(sys.argv[1]).read_text())
out = Path(sys.argv[2])
C = ["#2a78d6", "#eb6834", "#1baf7a"]
INK, INK2, GRID = "#1f1f1e", "#5f5e5a", "#e6e5e0"
plt.rcParams.update({"font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
                     "ytick.color": INK, "axes.spines.top": False, "axes.spines.right": False,
                     "font.family": ["DejaVu Sans"]})
short = {"ar_dc": "Argon DC glow\nNx 200", "ar_photo": "Argon photoemission\nNx 200", "n2_dbd": "Nitrogen DBD\nNx 1000",
         "d2_dbd": "Deuterium DBD\nNx 1000 (LXCat)", "n2_fine": "Nitrogen DBD\nNx 8000"}


def mean(case, mode, par):
    xs = [r["total_s"] for r in res["runs"] if r["case"] == case and r["mode"] == mode and r["parallel"] == par
          and not r.get("cold") and "error" not in r]
    return st.mean(xs)


cases = list(res["cases"])
series = [("Jupyter notebook", "notebook", False), ("Studio (GUI worker)", "studio", False),
          ("Studio, numba_parallel = True", "studio", True)]
fig, ax = plt.subplots(figsize=(7.0, 4.6), dpi=200)
h = 0.26
for k, (name, mode, par) in enumerate(series):
    ys = [i + (k - 1) * h for i in range(len(cases))]
    vals = [mean(c, mode, par) for c in cases]
    ax.barh(ys, vals, height=h - 0.04, color=C[k], label=name)
    for y, v in zip(ys, vals):
        ax.text(v + 0.4, y, f"{v:.1f} s", va="center", fontsize=7.5, color=INK2)
ax.set_yticks(range(len(cases)), [short[c] for c in cases])
ax.invert_yaxis()
ax.set_xlabel("End-to-end time per run [s]  (lower is faster)")
ax.xaxis.grid(True, color=GRID, linewidth=0.8)
ax.set_axisbelow(True)
ax.legend(loc="lower right", frameon=False, fontsize=8)
fig.tight_layout()
fig.savefig(out / "perf_runtime.png")

conc = res["concurrency"]
fig, ax = plt.subplots(figsize=(4.2, 2.4), dpi=200)
labels = [f"{c['level']} at a time" for c in conc]
vals = [c["wall_s"] for c in conc]
ax.barh(range(len(vals)), vals, height=0.55, color=C[0])
for i, v in enumerate(vals):
    ax.text(v + 0.6, i, f"{v:.1f} s  ({vals[0] / v:.1f}× throughput)", va="center", fontsize=7.5, color=INK2)
ax.set_yticks(range(len(vals)), labels)
ax.invert_yaxis()
ax.set_xlim(0, max(vals) * 1.55)
ax.set_xlabel(f"Wall time for {conc[0]['jobs']} Argon DC runs [s]")
ax.xaxis.grid(True, color=GRID, linewidth=0.8)
ax.set_axisbelow(True)
fig.tight_layout()
fig.savefig(out / "perf_concurrency.png")
