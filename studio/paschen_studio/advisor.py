"""Pre-flight checks, cost estimates and physics previews for a model.

* ``check_model`` runs PASCHEN-1D's own ``validate_simulation_config`` and adds
  practical advice (output size, run time, stability, gas/closure mismatches),
  each issue optionally carrying a one-click fix.
* ``estimate`` computes derived numbers shown in the GUI (dt, dx, E/N, pd ...).
* ``paschen_curve`` gives the classical Townsend breakdown estimate using the
  solver's *own* Townsend-coefficient builder, so it follows whatever α source
  (empirical formula or BOLSIG+ table) the model selects.
"""
from __future__ import annotations

import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

from . import schema as SC
from . import solver as S
from .units import format_quantity, human_bytes, human_duration

KB = 1.380649e-23
TORR = 133.32236842105263
TD = 1e-21


@dataclass
class Issue:
    level: str                    # error | warning | info | ok
    message: str
    path: str | None = None       # setting to jump to
    fix: str | None = None        # fix id
    fix_label: str = ""
    detail: str = ""


# ---------------------------------------------------------------------------
# Estimates
# ---------------------------------------------------------------------------
DEFAULT_RATE_COEFF = 6.5e5        # macro steps/s ~ C / Nx  (calibrated on a laptop core)


def estimate(model, measured_rate_coeff: float | None = None) -> dict[str, Any]:
    v = model.values()
    Nt = int(v["numerics.Nt"])
    Nx = int(v["numerics.Nx"])
    T = float(v["run.T_total"])
    L = float(v["geometry.L"])
    save_every = max(1, int(v["output.save_every"]))
    dt = T / max(Nt - 1, 1)
    dx = L / max(Nx - 1, 1)
    nsave = (Nt - 1) // save_every + 1
    log_int = bool(v["output.log_intermediate"])
    n_spatial = 4 + (10 if log_int else 0)
    has_node = v["circuit.circuit_type"] != "dielectric_plasma"
    n_f64 = 7 + (1 if has_node else 0)        # V_gap, I_* (6) [+ V_node]
    n_f32 = 9                                 # cfl, diffusion, picard, adaptive x4 ...
    bytes_scalar = Nt * (8 * n_f64 + 4 * n_f32)
    bytes_spatial = nsave * Nx * 4 * n_spatial
    p = float(v["plasma_state.p_Torr"])
    Ti = max(float(v["plasma_state.T_i"]), 1.0)
    N = p * TORR / (KB * Ti)
    Vp = abs(float(v.get("waveform.V_peak", 0.0)))
    if v["waveform.waveform_type"] == "rf":
        Vp = abs(float(v["waveform.V_peak"])) + abs(float(v["waveform.V_dc"]))
    E_mean = Vp / L if L > 0 else float("nan")
    coeff = measured_rate_coeff or DEFAULT_RATE_COEFF
    rate = coeff / max(Nx, 50)
    if v["numerics.hotloop_backend"] != "numba":
        rate *= 0.25
    runtime = (Nt - 1) / rate if rate > 0 else float("nan")
    return dict(
        Nt=Nt, Nx=Nx, T_total=T, L=L, dt=dt, dx=dx, nsave=nsave, save_every=save_every,
        bytes_total=bytes_scalar + bytes_spatial, bytes_scalar=bytes_scalar, bytes_spatial=bytes_spatial,
        neutral_density=N, pd_Torr_cm=p * L * 100.0, E_over_N_Td=(E_mean / N / TD) if N > 0 else float("nan"),
        E_mean=E_mean, runtime_s=runtime, steps_per_s=rate,
    )


def transport_estimate(model) -> dict[str, float]:
    """Mobility / diffusion at the mean applied field, via the solver's builders."""
    out: dict[str, float] = {}
    try:
        cfg = model.build_config()
        physics = S.import_solver_module("physics")
        est = estimate(model)
        x = np.linspace(0.0, est["L"], 5)
        E = np.full(5, max(est["E_mean"], 1.0), dtype=np.float32)
        N = float(physics.compute_background_neutral_density(cfg))
        mu_e = float(np.max(np.abs(physics.build_electron_mobility_profile(cfg, x, E, N))))
        D_e = float(np.max(np.abs(physics.build_electron_diffusion_profile(cfg, x, E, N))))
        out.update(mu_e=mu_e, D_e=D_e)
        dt, dx = est["dt"], est["dx"]
        out["cfl"] = mu_e * est["E_mean"] * dt / dx
        out["diff_number"] = D_e * dt / dx ** 2
    except Exception as exc:  # pragma: no cover - advice only
        out["error"] = str(exc)
    return out


# ---------------------------------------------------------------------------
# Paschen / Townsend breakdown estimate
# ---------------------------------------------------------------------------
def alpha_function(model) -> Callable[[np.ndarray, float], np.ndarray] | None:
    """Return f(E[V/m], p[Torr]) -> alpha [1/m] using the solver's own Townsend-alpha builder."""
    try:
        cfg = model.build_config()
        physics = S.import_solver_module("physics")
        Ti = max(float(cfg.plasma_state.T_i), 1.0)
        gas = cfg.plasma_state.gas

        def f(E: np.ndarray, p: float) -> np.ndarray:
            N = p * TORR / (KB * Ti)
            pr = p * 300.0 / Ti
            E = np.asarray(E, dtype=np.float32)
            return np.asarray(physics.build_townsend_alpha_profile(cfg, E, p, pr, gas, N), dtype=float)

        f(np.array([1e5]), float(cfg.plasma_state.p_Torr))  # smoke test
        return f
    except Exception:
        return None


def breakdown_voltage(alpha_f, p: float, d: float, gamma: float) -> float:
    if gamma <= 0:
        return float("inf")
    K = math.log(1.0 + 1.0 / gamma)
    V = np.logspace(0, 6.5, 1400)
    ad = alpha_f(V / d, p) * d
    ok = np.where(ad >= K)[0]
    if ok.size == 0:
        return float("inf")
    i = int(ok[0])
    if i == 0:
        return float(V[0])
    # log-interpolate between i-1 and i
    a0, a1 = ad[i - 1], ad[i]
    if a1 == a0:
        return float(V[i])
    frac = (K - a0) / (a1 - a0)
    return float(10 ** (np.log10(V[i - 1]) + frac * (np.log10(V[i]) - np.log10(V[i - 1]))))


def paschen_curve(model, npts: int = 60) -> dict[str, Any] | None:
    f = alpha_function(model)
    if f is None:
        return None
    v = model.values()
    d = float(v["geometry.L"])
    gamma = float(v["emission.gamma"])
    p0 = float(v["plasma_state.p_Torr"])
    pd0 = p0 * d * 100.0
    pds = np.logspace(math.log10(min(0.05, pd0 / 3)), math.log10(max(pd0 * 30, 50)), npts)
    ps = pds / (d * 100.0)
    Vb = np.array([breakdown_voltage(f, p, d, gamma) for p in ps])
    Vb0 = breakdown_voltage(f, p0, d, gamma)
    finite = np.isfinite(Vb)
    out = dict(pd=pds, Vb=Vb, pd0=pd0, Vb0=Vb0, gamma=gamma, d=d)
    if finite.any():
        j = int(np.nanargmin(np.where(finite, Vb, np.nan)))
        out.update(pd_min=float(pds[j]), Vb_min=float(Vb[j]))
    return out


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
_PATH_RE = re.compile(r"\b((?:run|numerics|geometry|plasma_state|plasma|local_field_approximation|"
                      r"electron_swarm_data|ion_transport|townsend_coefficient|ionization_frequency_source|"
                      r"recombination|waveform|boundary|circuit|emission|output|diagnostics)(?:\.[A-Za-z_0-9]+)+)")


def stability_estimate(model, v: dict | None = None) -> dict | None:
    """Drift CFL / diffusion number at the mean applied field and the sub-steps they require."""
    v = v or model.values()
    tr = transport_estimate(model)
    if "cfl" not in tr or not math.isfinite(tr["cfl"]):
        return None
    cfl, dn = float(tr["cfl"]), float(tr.get("diff_number", 0.0))
    need = math.ceil(max(cfl / max(float(v["numerics.target_cfl_substep"]), 1e-9),
                         dn / max(float(v["numerics.target_diffusion_cfl_substep"]), 1e-9), 1.0))
    return dict(cfl=cfl, diff=dn, need=need)


def solver_validation(model) -> list[Issue]:
    issues: list[Issue] = []
    try:
        cfg = model.build_config()
    except Exception as exc:
        return [Issue("error", f"Could not build the configuration: {exc}")]
    try:
        validation = S.import_solver_module("validation")
        validation.validate_simulation_config(cfg)
    except ValueError as exc:
        text = str(exc)
        lines = [ln[2:].strip() for ln in text.splitlines() if ln.startswith("- ")] or [text]
        for ln in lines:
            m = _PATH_RE.search(ln)
            path = m.group(1) if m else None
            if path and path not in model.schema.fields:
                # e.g. "circuit.R0_Rm_Cext requires ..." -> point at topology
                g = path.split(".")[0]
                cand = [p for p in model.schema.fields if p.startswith(g + ".")]
                path = cand[0] if cand else None
            iss = Issue("error", ln, path=path)
            if "only for argon and nitrogen" in ln:
                iss.path = iss.path or "plasma_state.gas"
                iss.fix, iss.fix_label = "auto_gas", "Use swarm tables for this gas"
            issues.append(iss)
    except FileNotFoundError as exc:
        issues.append(Issue("error", str(exc)))
    except Exception as exc:  # pragma: no cover
        issues.append(Issue("error", f"{type(exc).__name__}: {exc}"))
    return issues


def table_checks(model) -> list[Issue]:
    issues: list[Issue] = []
    v = model.values()
    physics = None
    try:
        physics = S.import_solver_module("physics")
    except Exception:
        return issues
    for path in SC.electron_tables_in_use(v):
        val = v.get(path)
        try:
            physics.load_electron_swarm_table(val) if hasattr(physics, "load_electron_swarm_table") else \
                physics.load_electron_mobility_muN_data(val)
        except Exception as exc:
            issues.append(Issue("error", f"Electron table '{val}': {exc}", path=path))
    it = None
    for path in SC.ion_tables_in_use(v):
        val = v.get(path)
        if not val:
            issues.append(Issue("error", "Select an ion table (the source mode requires one).", path=path,
                                fix="auto_ion", fix_label="Pick a matching ion table"))
            continue
        try:
            it = it or S.import_solver_module("ion_transport")
            dp = S.import_solver_module("data_paths")
            it.load_ion_transport_table(dp.resolve_ion_swarm_data_file(val))
        except Exception as exc:
            issues.append(Issue("error", f"Ion table '{val}': {exc}", path=path))
    return issues


def check_model(model, workspace: Path | None = None, measured_rate_coeff: float | None = None,
                deep: bool = True) -> list[Issue]:
    issues = solver_validation(model)
    v = model.values()
    est = estimate(model, measured_rate_coeff)

    gas = str(v["plasma_state.gas"])
    user_e = v["plasma.electron_kinetics_model"] == "user_defined_electron_kinetics" or (
        v["plasma.electron_kinetics_model"] == "local_field_approximation"
        and v["local_field_approximation.electron_transport_source"] == "user_defined_equation")
    user_alpha = v["plasma.impact_ionization_model"] == "from_townsend_alpha" and \
        v["townsend_coefficient.townsend_alpha_source_mode"] == "user_defined_equation"
    user_ion = v["plasma.ion_kinetics_model"] == "user_defined_ion_kinetics"
    if not S.has_empirical_closures(gas) and (user_e or user_alpha or user_ion) and \
            not any(i.fix == "auto_gas" for i in issues):
        issues.append(Issue(
            "error",
            f"The built-in empirical equations cover argon and nitrogen only, but the gas is '{gas}'. "
            "Use the bundled swarm tables for this gas.", path="plasma_state.gas",
            fix="auto_gas", fix_label=f"Use {gas} swarm tables"))

    if v["emission.enable_external_emission"]:
        for elec in ("cathode", "anode"):
            mechs = SC.emission_mechanisms(v, elec)
            if mechs and v[f"boundary.{elec}_electron_boundary"] != "electron_emission":
                issues.append(Issue(
                    "error", f"Emission is enabled on the {elec}, so its electron boundary must be "
                    "'electron emission'.", path=f"boundary.{elec}_electron_boundary",
                    fix=f"emit_bc_{elec}", fix_label="Set electron-emission boundary"))
            if v.get(f"emission.enable_{elec}_external_emission") and not mechs:
                issues.append(Issue("warning", f"The {elec} is set to emit but no mechanism is selected.",
                                    path=f"emission.enable_{elec}_external_emission"))

    if deep:
        issues += table_checks(model)

    # --- cost --------------------------------------------------------------
    total = est["bytes_total"]
    lvl = "info"
    if total > 4 * 1024 ** 3:
        lvl = "warning"
    issues.append(Issue(lvl, f"Output size ≈ {human_bytes(total)} "
                             f"({est['nsave']:,} snapshots × {est['Nx']} points, {est['Nt']:,} time steps).",
                        path="output.save_every" if est["bytes_spatial"] > est["bytes_scalar"] else "numerics.Nt"))
    if workspace is not None:
        try:
            free = shutil.disk_usage(workspace if workspace.exists() else workspace.parent).free
            if total > 0.9 * free:
                issues.append(Issue("error", f"Not enough free disk space in the workspace "
                                             f"({human_bytes(free)} free).", path="numerics.Nt"))
        except OSError:
            pass
    st0 = stability_estimate(model, v) if deep else None
    runtime = est["runtime_s"]
    sub_note = ""
    if st0 is not None and v["numerics.use_adaptive_substepping"] and st0["need"] > 1:
        n_sub = min(st0["need"], int(v["numerics.max_substeps"]))
        runtime *= n_sub
        sub_note = f", ≈{n_sub} sub-steps/step expected"
    issues.append(Issue("info", f"dt = {format_quantity(est['dt'], 's')}, dx = {format_quantity(est['dx'], 'm')}, "
                                f"estimated run time ≈ {human_duration(runtime)} "
                                f"(≈{est['steps_per_s']:,.0f} steps/s{sub_note}).", path="numerics.Nt"))
    if est["nsave"] > 20000:
        issues.append(Issue("warning", f"{est['nsave']:,} spatial snapshots will be saved; a few thousand are "
                                       "usually enough.", path="output.save_every",
                            fix="snapshots_2000", fix_label="Save ≈2000 snapshots"))
    if est["nsave"] < 20:
        issues.append(Issue("warning", f"Only {est['nsave']} spatial snapshots will be saved.",
                            path="output.save_every", fix="snapshots_500", fix_label="Save ≈500 snapshots"))

    # --- stability ------------------------------------------------------------
    if deep:
        st = stability_estimate(model, v)
        if st is not None:
            cfl, dn, need = st["cfl"], st["diff"], st["need"]
            adaptive = bool(v["numerics.use_adaptive_substepping"])
            if not adaptive and (cfl > 1.0 or dn > 0.5):
                issues.append(Issue(
                    "warning",
                    f"Likely numerically unstable: at the applied field the drift CFL ≈ {cfl:.2g} and the explicit "
                    f"diffusion number ≈ {dn:.2g} (limits ≈ 1 and 0.5) while adaptive sub-stepping is off.",
                    path="numerics.use_adaptive_substepping", fix="adaptive_on",
                    fix_label="Enable adaptive sub-stepping", detail="unstable"))
            elif adaptive and need > int(v["numerics.max_substeps"]):
                issues.append(Issue(
                    "warning",
                    f"Estimated ≈ {need} sub-steps per time step are needed at the applied field, above the cap of "
                    f"{v['numerics.max_substeps']} (drift CFL ≈ {cfl:.2g}, diffusion number ≈ {dn:.2g}).",
                    path="numerics.max_substeps", fix="adaptive_on", fix_label=f"Raise the cap to {min(1024, int(need * 3) + 1)}",
                    detail="unstable"))
    # --- breakdown estimate ---------------------------------------------------
    run_name = str(v["run.run_name"])
    if workspace is not None and (workspace / run_name).exists():
        issues.append(Issue("warning", f"A run folder named '{run_name}' already exists in the workspace; "
                                       "you will be asked to overwrite it or keep both.", path="run.run_name",
                            fix="unique_name", fix_label="Use a new run name"))
    if not any(i.level == "error" for i in issues):
        issues.insert(0, Issue("ok", "No errors – ready to run." if any(i.level == "warning" for i in issues) else "Model check passed – ready to run."))
    return issues


# ---------------------------------------------------------------------------
# Fixes
# ---------------------------------------------------------------------------
def apply_fix(model, fix: str, workspace: Path | None = None) -> list[str]:
    """Apply a fix in place; returns the changed setting paths."""
    v = model.values()
    changed: list[str] = []

    def setv(p, val):
        if model.set(p, val):
            changed.append(p)

    if fix == "auto_gas":
        changed += auto_configure_gas(model, str(v["plasma_state.gas"]))
    elif fix == "auto_ion":
        changed += auto_configure_ions(model, str(v["plasma_state.gas"]))
    elif fix.startswith("emit_bc_"):
        setv(f"boundary.{fix[8:]}_electron_boundary", "electron_emission")
    elif fix == "adaptive_on":
        setv("numerics.use_adaptive_substepping", True)
        st = stability_estimate(model)
        if st is not None and st["need"] > int(model.value("numerics.max_substeps")):
            setv("numerics.max_substeps", int(min(1024, int(st["need"] * 3) + 1)))
    elif fix.startswith("snapshots_"):
        n = int(fix.split("_")[1])
        setv("output.save_every", max(1, (int(v["numerics.Nt"]) - 1) // max(n - 1, 1)))
    elif fix == "unique_name" and workspace is not None:
        from .model import unique_run_name
        setv("run.run_name", unique_run_name(str(v["run.run_name"]), workspace))
    return changed


def electron_table_for_gas(gas: str) -> str | None:
    key = S.canonical_gas(gas)
    for t in S.electron_tables():
        if str(t.get("canonical_gas", "")).lower() == key:
            return t["basename"]
    return None


def ion_choice_for_gas(gas: str, Ti: float) -> dict | None:
    """Best bundled ion selection for a gas: native matched pair > native mobility+Einstein > others."""
    pairs = [p for p in S.ion_pairs_for_gas(gas) if abs(float(p.get("gas_temperature_K", 300)) - Ti) <= 5.0]
    mob = [r for r in S.ion_mobility_tables_for_gas(gas)
           if abs(float(r.get("gas_temperature_K", 300)) - Ti) <= 5.0]
    nat_pair = [p for p in pairs if S.ion_is_native(p["ion"], p["neutral"])]
    nat_mob = [r for r in mob if S.ion_is_native(r["ion"], r["neutral"])]
    if nat_pair:
        p = nat_pair[0]
        return dict(kind="pair", ion=p["ion"], mobility=Path(p["mobility_file"]).name,
                    diffusion=Path(p["diffusion_file"]).name, record=p)
    if nat_mob:
        r = nat_mob[0]
        return dict(kind="einstein", ion=r["ion"], mobility=Path(r["normalized_file"]).name, diffusion=None,
                    record=r)
    if pairs:
        p = pairs[0]
        return dict(kind="pair", ion=p["ion"], mobility=Path(p["mobility_file"]).name,
                    diffusion=Path(p["diffusion_file"]).name, record=p)
    if mob:
        r = mob[0]
        return dict(kind="einstein", ion=r["ion"], mobility=Path(r["normalized_file"]).name, diffusion=None,
                    record=r)
    return None


def auto_configure_ions(model, gas: str) -> list[str]:
    changed = []
    v = model.values()
    ch = ion_choice_for_gas(gas, float(v["plasma_state.T_i"]))
    if ch is None:
        return changed
    ion = str(ch["ion"]).replace("^", "")
    sets = [("plasma.ion_kinetics_model", "local_field_ion_kinetics"),
            ("ion_transport.positive_ion", ion),
            ("ion_transport.mobility_source_mode", "swarm_data_table_interpolation"),
            ("ion_transport.diffusion_source_mode",
             "swarm_data_table_interpolation" if ch["kind"] == "pair" else "einstein_relation"),
            ("ion_transport.mobility_table_path", ch["mobility"]),
            ("ion_transport.diffusion_table_path", ch["diffusion"]),
            ("ion_transport.out_of_range_policy", "clip")]
    for path, val in sets:
        if model.set(path, val):
            changed.append(path)
    return changed


def auto_configure_gas(model, gas: str) -> list[str]:
    """Point every electron/ion closure at the bundled tables for ``gas``."""
    changed: list[str] = []
    if model.set("plasma_state.gas", gas):
        changed.append("plasma_state.gas")
    table = electron_table_for_gas(gas)
    if S.has_empirical_closures(gas) and table is None:
        return changed
    if table:
        for path, val in [("plasma.electron_kinetics_model", "local_field_approximation"),
                          ("local_field_approximation.electron_transport_source", "swarm_data_table_interpolation"),
                          ("local_field_approximation.electron_swarm_data_path", table),
                          ("townsend_coefficient.townsend_alpha_source_mode", "interpolate_from_e_over_n_table"),
                          ("townsend_coefficient.townsend_alpha_swarm_data_path", table),
                          ("ionization_frequency_source.ionization_frequency_source_mode",
                           "interpolate_from_e_over_n_table"),
                          ("ionization_frequency_source.ionization_frequency_swarm_data_path", table)]:
            if model.set(path, val):
                changed.append(path)
    changed += auto_configure_ions(model, gas)
    # new transport coefficients can change the stable time step completely
    st = stability_estimate(model)
    if st is not None and (st["cfl"] > 0.5 or st["diff"] > 0.45 or st["need"] > 1):
        changed += apply_fix(model, "adaptive_on")
    return changed


# ---------------------------------------------------------------------------
# Preview data
# ---------------------------------------------------------------------------
def waveform_preview(model, npts: int = 2500) -> tuple[np.ndarray, np.ndarray] | None:
    try:
        cfg = model.build_config()
        physics = S.import_solver_module("physics")
        T = float(cfg.run.T_total)
        t = np.linspace(0.0, T, npts)
        extra = []
        if cfg.waveform.waveform_type == "step":
            for te in (cfg.waveform.tV_start, cfg.waveform.tV_end):
                if 0 <= te <= T:
                    extra += [te * (1 - 1e-9), te, te * (1 + 1e-9) if te > 0 else 1e-30]
        t = np.unique(np.concatenate([t, np.array(extra)])) if extra else t
        f = physics.make_voltage_waveform(cfg)
        return t, np.asarray(f(t), dtype=float)
    except Exception:
        return None


def electron_table_preview(path_value: str) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    physics = S.import_solver_module("physics")
    out = {}
    for label, key in [("Mobility *N (1/m/V/s)", "muN"), ("Diffusion coefficient *N (1/m/s)", "DN"),
                       ("Townsend ioniz. coef. alpha/N (m2)", "alphaN"), ("Mean energy (eV)", "energy")]:
        try:
            out[key] = physics.load_swarm_data_section(path_value, label)
        except Exception:
            pass
    return out


def ion_table_preview(path_value: str) -> tuple[np.ndarray, np.ndarray, dict] | None:
    try:
        it = S.import_solver_module("ion_transport")
        dp = S.import_solver_module("data_paths")
        tab = it.load_ion_transport_table(dp.resolve_ion_swarm_data_file(path_value))
        x = np.asarray(tab.reduced_field_Td, dtype=float)
        y = np.asarray(tab.reduced_transport_SI, dtype=float)
        md = dict(getattr(tab, "metadata", {}) or {})
        info = {k: md[k] for k in ("ion", "neutral", "quantity", "dataset_id", "gas_temperature_K",
                                   "reference", "database") if k in md}
        return x, y, info
    except Exception:
        return None
