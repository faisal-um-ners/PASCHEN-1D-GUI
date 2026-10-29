"""Automated tests for PASCHEN-1D Studio.  Run:  python -m pytest studio/tests -q"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDIO))

from paschen_studio import solver as S  # noqa: E402

ROOT = S.find_solver_root()
pytestmark = pytest.mark.skipif(ROOT is None, reason="PASCHEN-1D folder not found")
if ROOT is not None:
    S.set_solver_root(ROOT)

from paschen_studio import advisor as A  # noqa: E402
from paschen_studio import schema as SC  # noqa: E402
from paschen_studio.model import StudioModel, new_model_from_case  # noqa: E402
from paschen_studio.units import format_quantity, parse_quantity  # noqa: E402


def test_cases_and_schema():
    cases = S.list_cases()
    assert len(cases) >= 5
    for c in cases:
        sc = S.load_schema(c.module)
        assert len(sc.fields) > 150
        assert "geometry.L" in sc.fields and sc.fields["geometry.L"].kind == "float"
        assert sc.fields["circuit.circuit_type"].kind == "choice"
        assert sc.fields["boundary.enable_volume_sources"].kind == "bool"
        # every field has presentation metadata
        for p, fi in sc.fields.items():
            assert SC.meta_for(p, fi.comment).label


def test_units_roundtrip():
    for v, u in [(1.6e-11, "F"), (3.5e-3, "m"), (7e-5, "s"), (4e5, "Ω"), (231.0, "V"), (13.56e6, "Hz")]:
        assert math.isclose(parse_quantity(format_quantity(v, u, digits=12), u), v, rel_tol=1e-9)
    assert parse_quantity("16 pF", "F") == pytest.approx(1.6e-11)
    assert parse_quantity("16p", "F") == pytest.approx(1.6e-11)
    assert parse_quantity("2 cm", "m") == pytest.approx(0.02)
    assert parse_quantity("0.4 MOhm", "Ω") == pytest.approx(4e5)
    assert math.isinf(parse_quantity("inf", "F"))


def test_model_roundtrip(tmp_path):
    m = new_model_from_case("config_case_argon_dc_discharge")
    m.set("waveform.V_peak", 160.0)
    m.set("circuit.C_s", float("inf"))
    m.set("diagnostics.temporal.quantities", ("V_app", "V_gap"))
    assert m.is_modified("waveform.V_peak")
    p = m.save(tmp_path / "x.p1d.json")
    d = json.loads(p.read_text())
    assert d["overrides"]["circuit.C_s"] == "inf"
    m2 = StudioModel.load(p)
    assert m2.value("waveform.V_peak") == 160.0
    assert math.isinf(m2.value("circuit.C_s"))
    assert m2.value("diagnostics.temporal.quantities") == ("V_app", "V_gap")
    cfg = m2.build_config()
    assert cfg.waveform.V_peak == 160.0
    # setting back to the default removes the override; undo restores it
    m2.set("waveform.V_peak", m2.default("waveform.V_peak"))
    assert not m2.is_modified("waveform.V_peak")
    m2.undo()
    assert m2.value("waveform.V_peak") == 160.0
    script = m2.to_python_script()
    assert "cfg.waveform.V_peak = 160.0" in script and "float('inf')" in script


@pytest.mark.parametrize("case", ["config_case_argon_dc_discharge", "config_case_nitrogen_pulsed_discharge",
                                  "config_case_deuterium_pulsed_discharge",
                                  "config_case_helium_photoemission_discharge",
                                  "config_case_argon_photoemission_discharge"])
def test_cases_pass_check(case):
    issues = A.check_model(StudioModel(case))
    assert not [i for i in issues if i.level == "error"], [i.message for i in issues]


def test_relevance_rules():
    v = StudioModel("config_case_nitrogen_pulsed_discharge").values()
    assert SC.field_active("waveform.tau", v)[0]          # gaussian
    assert not SC.field_active("waveform.tV_end", v)[0]
    assert not SC.field_active("circuit.R0", v)[0]         # dielectric_plasma
    v2 = StudioModel("config_case_argon_photoemission_discharge").values()
    assert SC.field_active("emission.shared_laser_U_J", v2)[0]
    assert not SC.field_active("emission.cathode_laser_U_J", v2)[0]   # shared mode


def test_gas_autoconfig_and_fix():
    m = StudioModel("config_case_argon_dc_discharge")
    m.set("plasma_state.gas", "neon")
    assert any(i.level == "error" for i in A.check_model(m))
    A.apply_fix(m, "auto_gas")
    assert not any(i.level == "error" for i in A.check_model(m))
    assert m.value("plasma.electron_kinetics_model") == "local_field_approximation"
    assert "ne" in str(m.value("local_field_approximation.electron_swarm_data_path"))


def test_paschen_estimate():
    pc = A.paschen_curve(StudioModel("config_case_argon_dc_discharge"))
    assert pc is not None and 100 < pc["Vb0"] < 200


def _job(tmp_path, nt=1500, name="t"):
    m = StudioModel("config_case_nitrogen_pulsed_discharge")
    m.set("numerics.Nx", 120)
    m.set("numerics.Nt", nt)
    m.set("run.T_total", 1e-12 * (nt - 1))
    m.set("output.save_every", 10)
    job = {"model": m.to_dict(), "workspace": str(tmp_path), "run_name": name, "solver_root": str(ROOT)}
    jf = tmp_path / f"{name}.json"
    jf.write_text(json.dumps(job))
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(STUDIO), str(ROOT)]))
    return jf, env


def test_worker_run(tmp_path):
    jf, env = _job(tmp_path)
    out = subprocess.run([sys.executable, "-u", "-m", "paschen_studio.worker", str(jf)], capture_output=True,
                         text=True, env=env, timeout=600)
    assert out.returncode == 0, out.stdout[-3000:]
    st = json.loads((tmp_path / "t" / "studio_run.json").read_text())
    assert st["status"] == "finished"
    assert (tmp_path / "t" / "run_metadata.json").exists()
    from paschen_studio.runs import RunData, discover
    rd = RunData.open(tmp_path / "t")
    t, v = rd.temporal("V_gap")
    assert len(t) > 10
    assert discover([tmp_path])[0].status == "finished"


def test_worker_stop(tmp_path):
    jf, env = _job(tmp_path, nt=400000, name="s")
    p = subprocess.Popen([sys.executable, "-u", "-m", "paschen_studio.worker", str(jf)], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, env=env)
    ctl = tmp_path / "s" / ".studio_control"
    t0 = time.time()
    for line in p.stdout:
        if '"event": "progress"' in line and time.time() - t0 > 1:
            ctl.write_text("stop")
            break
    p.wait(timeout=300)
    st = json.loads((tmp_path / "s" / "studio_run.json").read_text())
    assert st["status"] == "stopped" and st["stopped_early"]
    assert (tmp_path / "s" / "run_metadata.json").exists()


def test_cli_check_and_cases():
    env = dict(os.environ, PYTHONPATH=str(STUDIO))
    out = subprocess.run([sys.executable, "-m", "paschen_studio", "cases"], capture_output=True, text=True,
                         env=env, timeout=120)
    assert out.returncode == 0 and "config_case_argon_dc_discharge" in out.stdout
    out = subprocess.run([sys.executable, "-m", "paschen_studio", "check",
                          str(STUDIO / "examples" / "nitrogen_dbd_demo.p1d.json")],
                         capture_output=True, text=True, env=env, timeout=120)
    assert out.returncode == 0, out.stdout


def test_gui_smoke():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.setOrganizationName("PASCHEN-1D-tests")
    from paschen_studio.gui.app import setup_application
    app = setup_application(theme_name="light")
    from paschen_studio.gui.main_window import MainWindow
    w = MainWindow()
    for i in range(5):
        w.go(i)
        app.processEvents()
    w.model_page.select_group("emission")
    w.model_page.focus_setting("circuit.R0")
    for key in ("quickstart", "guide", "tutorial", "readme", "ions", "shortcuts", "cite"):
        w.show_help(key)
        app.processEvents()
        assert w.help.browser.document().toPlainText().strip()
    w.help.find.edit.setText("PASCHEN")
    assert w.help.find.matches
    w.close()


def test_doc_rendering_keeps_text_after_images():
    """Qt's markdown reader drops text after raw HTML; the help viewer must not."""
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from paschen_studio.gui.app import setup_application
    setup_application(theme_name="light")
    from paschen_studio.gui.help_page import DocBrowser, clean_markdown
    md = "# T\n\ntext before\n\n<img src=\"images/x.png\" width=\"900\" alt=\"X\">\n\n**after** the image\n\n```\ncode line\n```\n"
    assert "<img" not in clean_markdown(md) and "![X](images/x.png)" in clean_markdown(md)
    b = DocBrowser()
    b.show_markdown(md, STUDIO / "docs")
    text = b.document().toPlainText()
    assert "after the image" in text and "code line" in text
    guide = (STUDIO / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    b.show_markdown(guide, STUDIO / "docs")
    assert "All settings – blocks (left)" in b.document().toPlainText()   # text after the Model-page images
    assert len(b.headings) > 5


def test_guide_text_wraps_and_lists():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from paschen_studio.gui.app import setup_application
    setup_application(theme_name="light")
    from paschen_studio.gui.widgets import GuideText, md_to_html, CodeBlock
    html = md_to_html("### CircuitConfig\n\nPara one\ncontinues.\n\n- item one\n  continues here\n- item two\n\nAfter list.")
    assert "CircuitConfig" not in html
    assert html.count("<li") == 2 and "continues here" in html and "<p" in html
    g = GuideText("Intro\n\n```\nV_app(t) -- R0 -- V_node -- R_m -- V_gap -- a very long diagram line\n```\n\nEnd.")
    blocks = g.findChildren(CodeBlock)
    assert len(blocks) == 1 and blocks[0].minimumSizeHint().width() <= 60


def test_export_dialog_options(tmp_path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from paschen_studio.gui.app import setup_application
    app = setup_application(theme_name="light")
    import numpy as np
    from paschen_studio.gui.plotting import AxesSpec, FigureSpec, PlotCanvas, Series
    from paschen_studio.gui.export_dialog import (ExportDialog, export_figure, parse_ticks, preview_png, tex_safe,
                                                  to_mathtext)
    assert to_mathtext("Gap voltage V_gap") == r"Gap voltage $V_\mathrm{gap}$"
    assert to_mathtext("densities [m⁻³]") == "densities [m$^{-3}$]"
    assert "$$" not in tex_safe("μ·N [1/(m·V·s)]")
    assert parse_ticks("0, 5,10") == [0.0, 5.0, 10.0] and parse_ticks("") is None
    x = np.linspace(0, 1e-7, 50)
    spec = FigureSpec([AxesSpec(title="Voltages", xlabel="time [ns]", ylabel="voltages [kV]",
                                series=[Series(x * 1e9, 1 + np.sin(x * 3e7), label="Applied voltage V_app"),
                                        Series(x * 1e9, 2 + np.cos(x * 3e7), label="Gap voltage V_gap")])])
    c = PlotCanvas("", export_name="v")
    c.set_spec(spec, keep_view=False)
    dlg = ExportDialog(c, c._spec, c.current_view(), "v")
    dlg._update_preview()
    assert dlg.p_y.text() == "voltages [kV]" and dlg.p_title.text() == ""          # no title unless typed
    assert dlg.curve_w[1]["text"].text() == r"Gap voltage $V_\mathrm{gap}$"
    assert dlg.ax_w["x"]["lo"].text() != "" and dlg.ax_w["x"]["ticks"].text() != ""  # filled from the figure
    dlg.p_y.setText(r"$V$ (kV)")
    dlg.curve_w[0]["text"].setText("")                    # drop a curve from the legend
    dlg.curve_w[1]["marker"].setCurrentIndex(1)
    dlg.ax_w["x"]["ticks"].setText("0, 50, 100")
    dlg._ticks_typed("x")
    dlg.ax_w["y"]["scale"].setCurrentIndex(1)             # log y: smart decade range
    dlg.lg_pos.setCurrentIndex(10)                        # outside right
    opts = dlg.options()
    p = opts.panels[0]
    assert p.ylabel == r"$V$ (kV)" and p.yscale == "log" and p.ylim[0] > 0
    assert not p.xticks_auto and parse_ticks(p.xticks) == [0.0, 50.0, 100.0]
    assert p.curves[1].marker == "o" and p.curves[0].label == ""
    png, ticks = preview_png(c._spec, opts, 80, with_ticks=True)
    assert png[:4] == b"\x89PNG" and ticks[0][0] == [0.0, 50.0, 100.0]
    for ext in ("pdf", "png", "svg"):
        opts.fmt = ext
        out = export_figure(c._spec, opts, str(tmp_path / f"fig.{ext}"))
        assert os.path.getsize(out) > 1000
    st = dlg.state()
    dlg2 = ExportDialog(c, c._spec, c.current_view(), "v", state=st)
    assert dlg2.p_y.text() == r"$V$ (kV)"
