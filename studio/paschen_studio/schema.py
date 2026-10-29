"""Presentation metadata for the PASCHEN-1D configuration.

The *structure* (groups, fields, types, comments) is read from the solver at run
time (see :mod:`paschen_studio.solver`).  This module only adds the human layer:
friendly labels, physical units, which settings are advanced, how a group is
split into sections, and which settings are relevant for the current choices
(e.g. ``tau`` only matters for a Gaussian waveform).

Unknown fields (added in a future PASCHEN-1D release) are still shown, with an
automatically generated label, so the studio never hides a solver option.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Model-builder tree
# ---------------------------------------------------------------------------
# (section title, [(group path, display name, icon key)])
TREE: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("Study", [
        ("run", "Run & duration", "clock"),
        ("numerics", "Mesh & time stepping", "grid"),
    ]),
    ("Plasma physics", [
        ("geometry", "Geometry", "gap"),
        ("plasma_state", "Gas & initial plasma", "gas"),
        ("plasma", "Physics models", "atom"),
        ("local_field_approximation", "Electron transport (LFA)", "electron"),
        ("electron_swarm_data", "Electron table policy", "table"),
        ("ion_transport", "Ion transport", "ion"),
        ("townsend_coefficient", "Townsend coefficient α", "alpha"),
        ("ionization_frequency_source", "Ionization frequency νᵢ", "nu"),
        ("recombination", "Recombination", "recomb"),
    ]),
    ("Drive & surfaces", [
        ("waveform", "Applied voltage", "wave"),
        ("circuit", "External circuit", "circuit"),
        ("boundary", "Boundary conditions", "boundary"),
        ("emission", "Surface emission", "emission"),
    ]),
    ("Output", [
        ("output", "Output & logging", "output"),
        ("diagnostics.temporal", "Notebook plots: temporal", "chart"),
        ("diagnostics.spatial", "Notebook plots: spatial", "chart"),
        ("diagnostics.averaged_spatial", "Notebook plots: averaged", "chart"),
    ]),
]

GROUP_TITLES = {g: t for _, items in TREE for g, t, _ in items}
GROUP_ICONS = {g: i for _, items in TREE for g, _, i in items}

GROUP_INTRO = {
    "run": "Name of the output folder and the physical time to simulate.",
    "numerics": "Spatial grid, time step and the adaptive sub-stepping that keeps the explicit "
                "transport update stable. dt = T_total / (Nt − 1), dx = L / (Nx − 1).",
    "geometry": "The 1D gap between the anode (x = 0) and the cathode (x = L). The area converts "
                "current density into current; a dielectric layer turns the gap into a DBD.",
    "plasma_state": "Neutral gas, pressure and temperatures. The neutral density N = p / (k_B T_i) "
                    "sets the reduced field E/N. n0 seeds a uniform initial plasma.",
    "plasma": "Choose the closures: how electron and ion transport coefficients and the "
              "impact-ionization rate are obtained.",
    "local_field_approximation": "Electron mobility and diffusion evaluated from the local reduced "
                                 "field E/N, using a bundled BOLSIG+ table or the equations in physics.py.",
    "electron_swarm_data": "Policy shared by every electron table: what happens outside the tabulated "
                           "E/N range and how strictly the table gas temperature must match T_i.",
    "ion_transport": "The positive ion drifting through the neutral gas. Use the empirical closures "
                     "(argon/nitrogen) or LXCat mobility/diffusion tables.",
    "townsend_coefficient": "Source of the Townsend coefficient α when νᵢ = α·|uₑ|.",
    "ionization_frequency_source": "Direct source of the ionization frequency νᵢ (bypasses α).",
    "recombination": "Volumetric electron–ion recombination sink S = β nₑ nᵢ.",
    "waveform": "The source voltage V_app(t). With an external circuit, the gap voltage differs "
                "from V_app.",
    "circuit": "Lumped external circuit that couples the source to the plasma gap.",
    "boundary": "Density closures at each electrode and the volumetric source switches.",
    "emission": "Ion-induced secondary emission (γ) plus optional external emission mechanisms on "
                "each electrode: constant current, Fowler–Nordheim, Murphy–Good, "
                "Richardson–Dushman thermionic and quantum-pulse photoemission.",
    "output": "How often snapshots are saved and which extra fields are logged. The Studio's "
              "live view and results browser read these files.",
    "diagnostics.temporal": "Defaults for the diagnostics notebooks. They do not change the "
                            "physics; the Studio's Results page offers the same plots interactively.",
    "diagnostics.spatial": "Defaults for the spatial-snapshot notebook plots.",
    "diagnostics.averaged_spatial": "Defaults for the time-/cycle-averaged notebook plots.",
}

# Settings that only matter when another switch/choice is on. The form indents them under that control, so
# the dependency is visible at a glance (and, in the Essentials view, they appear only when it is on).
PARENT_CONTROL = {
    "boundary.enable_ionization_source": "boundary.enable_volume_sources",
    "boundary.enable_recombination_sink": "boundary.enable_volume_sources",
    "numerics.target_cfl_substep": "numerics.use_adaptive_substepping",
    "numerics.target_diffusion_cfl_substep": "numerics.use_adaptive_substepping",
    "numerics.max_substeps": "numerics.use_adaptive_substepping",
    "numerics.adaptive_substep_overflow_policy": "numerics.use_adaptive_substepping",
    "numerics.adaptive_substep_warn_every": "numerics.use_adaptive_substepping",
    "numerics.numba_parallel": "numerics.hotloop_backend",
    "emission.enable_cathode_external_emission": "emission.enable_external_emission",
    "emission.enable_anode_external_emission": "emission.enable_external_emission",
    "emission.electrode_material_mode": "emission.enable_external_emission",
    "geometry.eps_r": "geometry.l",
}

ADVANCED_GROUPS = {"electron_swarm_data", "diagnostics.temporal", "diagnostics.spatial",
                   "diagnostics.averaged_spatial"}


# ---------------------------------------------------------------------------
# Field metadata
# ---------------------------------------------------------------------------
@dataclass
class Meta:
    label: str
    unit: str = ""
    advanced: bool = False
    section: str = ""
    hint: str = ""          # short plain-language help (the solver comment is shown as well)
    minimum: float | None = None
    integer_like: bool = False


M = Meta
FIELD_META: dict[str, Meta] = {
    # run
    "run.run_name": M("Run name (output folder)", hint="Each run is written to a folder with this name. "
                      "Use a new name whenever parameters change."),
    "run.T_total": M("Simulated time T_total", "s", hint="Physical end time of the simulation."),
    # numerics
    "numerics.Nx": M("Grid points Nx", section="Grid & time step", minimum=3),
    "numerics.Nt": M("Time steps Nt", section="Grid & time step", minimum=2,
                     hint="Macro time step dt = T_total/(Nt−1)."),
    "numerics.hotloop_backend": M("Compute backend", section="Performance"),
    "numerics.numba_parallel": M("Parallel Numba kernel", section="Performance", advanced=True),
    "numerics.use_adaptive_substepping": M("Adaptive sub-stepping", section="Adaptive sub-stepping"),
    "numerics.target_cfl_substep": M("Target drift CFL", section="Adaptive sub-stepping"),
    "numerics.target_diffusion_cfl_substep": M("Target diffusion number", section="Adaptive sub-stepping"),
    "numerics.max_substeps": M("Max sub-steps per step", section="Adaptive sub-stepping", minimum=1),
    "numerics.adaptive_substep_overflow_policy": M("If max sub-steps exceeded", section="Adaptive sub-stepping",
                                                   advanced=True),
    "numerics.adaptive_substep_warn_every": M("Warn every (steps)", section="Adaptive sub-stepping", advanced=True),
    "numerics.kt_limiter_theta": M("KT slope-limiter θ", section="Scheme", advanced=True),
    "numerics.bc_poisson_picard_min_iter": M("Picard min iterations", section="Scheme", advanced=True),
    "numerics.bc_poisson_picard_max_iter": M("Picard max iterations", section="Scheme", advanced=True),
    "numerics.bc_poisson_picard_tol": M("Picard tolerance", "V", section="Scheme", advanced=True),
    # geometry
    "geometry.L": M("Gap length L", "m", section="Gap"),
    "geometry.A": M("Electrode area A", "m²", section="Gap"),
    "geometry.l": M("Dielectric thickness l", "m", section="Dielectric layers",
                    hint="0 = bare metal electrodes. > 0 adds a dielectric layer on each electrode."),
    "geometry.eps_r": M("Relative permittivity εr", section="Dielectric layers"),
    # plasma_state
    "plasma_state.gas": M("Neutral gas", section="Gas"),
    "plasma_state.p_Torr": M("Pressure p", "Torr", section="Gas"),
    "plasma_state.T_i": M("Gas / ion temperature Tᵢ", "K", section="Gas"),
    "plasma_state.T_e": M("Electron temperature Tₑ", "K", section="Gas",
                          hint="Used by user-defined closures; no energy equation is solved."),
    "plasma_state.n0": M("Initial density n0", "m⁻³", section="Initial plasma",
                         hint="Uniform initial electron and ion density. 0 lets emission seed the discharge."),
    # plasma
    "plasma.electron_kinetics_model": M("Electron kinetics"),
    "plasma.ion_kinetics_model": M("Ion kinetics"),
    "plasma.impact_ionization_model": M("Impact ionization"),
    "plasma.recombination_model": M("Recombination model", advanced=True),
    # LFA
    "local_field_approximation.electron_transport_source": M("Electron μₑ, Dₑ source"),
    "local_field_approximation.electron_swarm_data_path": M("Electron swarm table"),
    "electron_swarm_data.out_of_range_policy": M("Outside table E/N range"),
    "electron_swarm_data.gas_temperature_tolerance_K": M("Gas-temperature tolerance", "K"),
    # ions
    "ion_transport.positive_ion": M("Positive ion", section="Ion species"),
    "ion_transport.mobility_source_mode": M("Mobility μᵢ source", section="Tables"),
    "ion_transport.diffusion_source_mode": M("Diffusion Dᵢ source", section="Tables"),
    "ion_transport.mobility_table_path": M("Mobility table", section="Tables"),
    "ion_transport.diffusion_table_path": M("Diffusion table", section="Tables"),
    "ion_transport.out_of_range_policy": M("Outside table E/N range", section="Table policy"),
    "ion_transport.gas_temperature_tolerance_K": M("Gas-temperature tolerance", "K", section="Table policy",
                                                   advanced=True),
    # townsend / nu_i / recombination
    "townsend_coefficient.townsend_alpha_source_mode": M("α source"),
    "townsend_coefficient.townsend_alpha_swarm_data_path": M("α/N table"),
    "ionization_frequency_source.ionization_frequency_source_mode": M("νᵢ source"),
    "ionization_frequency_source.ionization_frequency_swarm_data_path": M("νᵢ/N table"),
    "recombination.recombination_coefficient": M("Recombination coefficient β", "m³/s"),
    # waveform
    "waveform.waveform_type": M("Waveform", section="Shape"),
    "waveform.V_peak": M("Amplitude V_peak", "V", section="Shape"),
    "waveform.tV_start": M("Switch-on time", "s", section="Shape"),
    "waveform.tV_end": M("Switch-off time", "s", section="Shape"),
    "waveform.t_peak": M("Pulse centre t_peak", "s", section="Shape"),
    "waveform.tau": M("Pulse width τ", "s", section="Shape"),
    "waveform.f_rf": M("Frequency f", "Hz", section="Shape"),
    "waveform.V_dc": M("DC offset", "V", section="Shape"),
    "waveform.phi_rf": M("Phase φ at t = 0", "rad", section="Shape"),
    "waveform.table_path": M("Waveform file (CSV)", section="Table"),
    "waveform.table_time_column": M("Time column (0-based)", section="Table"),
    "waveform.table_voltage_column": M("Voltage column (0-based)", section="Table"),
    "waveform.table_time_scale": M("Time scale factor", section="Table"),
    "waveform.table_time_offset": M("Time offset", "s", section="Table"),
    "waveform.table_voltage_scale": M("Voltage scale factor", section="Table"),
    "waveform.table_voltage_offset": M("Voltage offset", "V", section="Table"),
    # boundary
    "boundary.anode_ion_boundary": M("Anode · ions", section="Electrode closures"),
    "boundary.anode_electron_boundary": M("Anode · electrons", section="Electrode closures"),
    "boundary.cathode_ion_boundary": M("Cathode · ions", section="Electrode closures"),
    "boundary.cathode_electron_boundary": M("Cathode · electrons", section="Electrode closures"),
    "boundary.enable_volume_sources": M("Volume sources", section="Volume sources"),
    "boundary.enable_ionization_source": M("Impact ionization", section="Volume sources"),
    "boundary.enable_recombination_sink": M("Recombination sink", section="Volume sources"),
    # circuit
    "circuit.circuit_type": M("Topology", section="Topology"),
    "circuit.circuit_time_scheme": M("Time integration", section="Topology"),
    "circuit.R0": M("Source resistance R0", "Ω", section="Elements"),
    "circuit.C_s": M("Series capacitor Cs", "F", section="Elements"),
    "circuit.L_s": M("Series inductor Ls", "H", section="Elements"),
    "circuit.C_p": M("Shunt capacitor Cp", "F", section="Elements"),
    "circuit.L_p": M("Shunt inductor Lp", "H", section="Elements"),
    "circuit.R_m": M("Load / measurement resistor Rm", "Ω", section="Elements"),
    "circuit.C_ext": M("Load-side stray capacitance C_ext", "F", section="Elements"),
    # output
    "output.save_every": M("Save a snapshot every … steps", minimum=1),
    "output.log_intermediate": M("Log fluxes, sources & transport"),
    "output.print_run_summary": M("Print run summary"),
    # diagnostics
    "diagnostics.temporal.enabled": M("Enabled"),
    "diagnostics.temporal.quantities": M("Quantities"),
    "diagnostics.temporal.plot_groups": M("Overlay groups (Python)", advanced=True),
    "diagnostics.temporal.t_start": M("Window start", "s"),
    "diagnostics.temporal.t_end": M("Window end", "s"),
    "diagnostics.temporal.savepath_prefix": M("Save-path prefix"),
    "diagnostics.spatial.enabled": M("Enabled"),
    "diagnostics.spatial.quantities": M("Quantities"),
    "diagnostics.spatial.plot_groups": M("Overlay groups (Python)", advanced=True),
    "diagnostics.spatial.t_samples": M("Sample times (s, comma separated)"),
    "diagnostics.spatial.x_unit": M("x-axis unit"),
    "diagnostics.spatial.savepath_prefix": M("Save-path prefix"),
    "diagnostics.averaged_spatial.enabled": M("Enabled"),
    "diagnostics.averaged_spatial.quantities": M("Quantities"),
    "diagnostics.averaged_spatial.plot_groups": M("Overlay groups (Python)", advanced=True),
    "diagnostics.averaged_spatial.mode": M("Averaging mode"),
    "diagnostics.averaged_spatial.t_avg_start": M("Window start", "s"),
    "diagnostics.averaged_spatial.t_avg_end": M("Window end", "s"),
    "diagnostics.averaged_spatial.N_cycle_avg": M("RF cycles to average"),
    "diagnostics.averaged_spatial.x_unit": M("x-axis unit"),
    "diagnostics.averaged_spatial.savepath_prefix": M("Save-path prefix"),
    # emission - common
    "emission.gamma": M("Ion-induced SEE yield γ (cathode)", section="Secondary emission"),
    "emission.anode_electron_induced_yield": M("Electron-induced yield δ (anode)", section="Secondary emission"),
    "emission.use_vaughan_sey": M("Use Vaughan δ(E) model at the anode", section="Secondary emission"),
    "emission.vaughan_effective_temperature_mode": M("Vaughan impact-energy temperature", section="Vaughan model"),
    "emission.vaughan_Emax0_eV": M("E_max0", "eV", section="Vaughan model"),
    "emission.vaughan_dmax0": M("δ_max0", section="Vaughan model"),
    "emission.vaughan_ks": M("Smoothness k_s", section="Vaughan model"),
    "emission.vaughan_z": M("z", section="Vaughan model"),
    "emission.vaughan_E0": M("E0", "eV", section="Vaughan model"),
    "emission.enable_external_emission": M("External emission", section="External emission",
                                            hint="Master switch for every external emission mechanism below."),
    "emission.electrode_material_mode": M("Electrode material parameters", section="External emission"),
    "emission.enable_anode_external_emission": M("Anode emits", section="External emission"),
    "emission.enable_cathode_external_emission": M("Cathode emits", section="External emission"),
}

MECHANISMS = [
    ("constant_J", "Constant current density"),
    ("fn", "Fowler–Nordheim field emission"),
    ("mg", "Murphy–Good field emission"),
    ("rd", "Richardson–Dushman thermionic"),
    ("quantum_pulse", "Quantum-pulse photoemission (laser)"),
]
MECH_TITLE = dict(MECHANISMS)

# base parameter name -> (mechanism, label, unit, advanced)
EMISSION_PARAMS: dict[str, tuple[str, str, str, bool]] = {
    "emission_J_const": ("constant_J", "Current density J", "A/m²", False),
    "emission_t_start": ("constant_J", "Start time", "s", False),
    "emission_t_end": ("constant_J", "End time", "s", False),
    "fn_work_function_eV": ("fn", "Work function φ", "eV", False),
    "fn_field_scale_factor": ("fn", "Field enhancement β", "", False),
    "mg_work_function_eV": ("mg", "Work function φ", "eV", False),
    "mg_field_scale_factor": ("mg", "Field enhancement β", "", False),
    "mg_f_clip_min": ("mg", "Scaled field f – min clip", "", True),
    "mg_f_clip_max": ("mg", "Scaled field f – max clip", "", True),
    "rd_A_R": ("rd", "Richardson constant A_R", "A/(m²K²)", False),
    "rd_emitter_K": ("rd", "Emitter temperature", "K", False),
    "rd_work_function_eV": ("rd", "Work function φ", "eV", False),
    "laser_t0": ("quantum_pulse", "Laser arrival time t₀", "s", False),
    "laser_U_J": ("quantum_pulse", "Pulse energy U", "J", False),
    "laser_tau_p_s": ("quantum_pulse", "Pulse duration τp", "s", False),
    "emission_lambda_m": ("quantum_pulse", "Wavelength λ", "m", False),
    "laser_theta_deg": ("quantum_pulse", "Incidence angle θ", "deg", False),
    "laser_wx_m": ("quantum_pulse", "Spot width wx", "m", False),
    "laser_wy_m": ("quantum_pulse", "Spot width wy", "m", False),
    "emission_W_eV": ("quantum_pulse", "Work function W", "eV", False),
    "emission_Ef_eV": ("quantum_pulse", "Fermi energy E_F", "eV", False),
    "emission_T": ("quantum_pulse", "Electrode temperature", "K", False),
    "emission_epsilon0_eV": ("quantum_pulse", "Energy-integration limit ε₀", "eV", True),
    "emission_k_ph": ("quantum_pulse", "Photon sidebands k (n = −k…k)", "", True),
    "laser_t_window_ps": ("quantum_pulse", "Pulse window half-width", "ps", True),
    "emission_dt_ps": ("quantum_pulse", "Pulse time step", "ps", True),
    "emission_eps_points": ("quantum_pulse", "Energy grid points", "", True),
    "emission_wt_points": ("quantum_pulse", "Phase grid points", "", True),
}

CHOICE_LABELS = {
    "numpy": "NumPy (portable)",
    "numba": "Numba JIT (fast)",
    "warn_and_cap": "Warn and cap",
    "error": "Stop with an error",
    "clip": "Clip to the table end-points",
    "user_defined_electron_kinetics": "User-defined equations (physics.py)",
    "local_field_approximation": "Local-field approximation (E/N)",
    "user_defined_ion_kinetics": "User-defined equations (physics.py)",
    "local_field_ion_kinetics": "Local-field ion kinetics (tables / Einstein)",
    "from_townsend_alpha": "From Townsend α  (νᵢ = α|uₑ|)",
    "from_ionization_frequency": "Direct ionization frequency νᵢ",
    "user_defined_constant_coefficient": "Constant coefficient β",
    "user_defined_equation": "User-defined equation (physics.py)",
    "swarm_data_table_interpolation": "Swarm-table interpolation",
    "interpolate_from_e_over_n_table": "E/N swarm-table interpolation",
    "einstein_relation": "Einstein relation  Dᵢ = μᵢ kTᵢ/e",
    "step": "Step (on/off pulse)",
    "gaussian": "Gaussian pulse",
    "dc": "DC (constant)",
    "rf": "RF sinusoid",
    "table": "Table from CSV file",
    "tabulated": "Tabulated (CSV)",
    "measured_table": "Measured waveform (CSV)",
    "zero_density": "Zero density (absorbing)",
    "implicit_drift_closure": "Implicit drift closure",
    "electron_emission": "Electron emission (emitting surface)",
    "explicit_euler": "Explicit Euler",
    "implicit_euler": "Implicit Euler (stiff circuits)",
    "mna": "MNA backward Euler (general)",
    "shared": "Same material for both electrodes",
    "separate": "Separate anode / cathode parameters",
    "fixed": "Fixed Tₑ from Gas settings",
    "time_window": "Time window",
    "last_n_cycles": "Last N RF cycles",
    "dielectric_plasma": "Dielectric + plasma (no lumped elements)",
    "R0_Cp": "R0 – Cp",
    "R0_Cp_Rm": "R0 – Cp – Rm",
    "R0_Rm_Cext": "R0 – Rm – C_ext",
    "R0_Cs_Cp": "R0 – Cs – Cp",
    "R0_Cs_Cp_Rm": "R0 – Cs – Cp – Rm",
    "R0_Cs_Ls_Cp": "R0 – Cs – Ls – Cp",
    "R0_Cs_Ls_Cp_Rm": "R0 – Cs – Ls – Cp – Rm",
    "R0_Cs_Ls_Cp_Lp": "R0 – Cs – Ls – Cp – Lp",
    "R0_Cs_Ls_Cp_Lp_Rm_Cext": "Full network R0–Cs–Ls–Cp–Lp–Rm–C_ext",
}

TOPOLOGY_ELEMENTS = {
    "dielectric_plasma": [],
    "R0_Cp": ["R0", "C_p"],
    "R0_Cp_Rm": ["R0", "C_p", "R_m"],
    "R0_Rm_Cext": ["R0", "R_m", "C_ext"],
    "R0_Cs_Cp": ["R0", "C_s", "C_p"],
    "R0_Cs_Cp_Rm": ["R0", "C_s", "C_p", "R_m"],
    "R0_Cs_Ls_Cp": ["R0", "C_s", "L_s", "C_p"],
    "R0_Cs_Ls_Cp_Rm": ["R0", "C_s", "L_s", "C_p", "R_m"],
    "R0_Cs_Ls_Cp_Lp": ["R0", "C_s", "L_s", "C_p", "L_p"],
    "R0_Cs_Ls_Cp_Lp_Rm_Cext": ["R0", "C_s", "L_s", "C_p", "L_p", "R_m", "C_ext"],
}

TABLE_FIELDS = {
    "local_field_approximation.electron_swarm_data_path": "electron",
    "townsend_coefficient.townsend_alpha_swarm_data_path": "electron",
    "ionization_frequency_source.ionization_frequency_swarm_data_path": "electron",
    "ion_transport.mobility_table_path": "ion_mobility",
    "ion_transport.diffusion_table_path": "ion_diffusion",
}

# Quantities used across the app (label, unit, colour role)
QUANTITY_INFO = {
    "V_app": ("Applied voltage V_app", "V"),
    "V_node": ("Node voltage V_node", "V"),
    "V_source": ("Source voltage", "V"),
    "V_gap": ("Gap voltage V_gap", "V"),
    "I_discharge": ("Discharge current I", "A"),
    "I_transport_plasma": ("Transport current (plasma)", "A"),
    "I_transport_circuit": ("Transport current (circuit)", "A"),
    "I_emission_circuit": ("Emission residual (circuit)", "A"),
    "I_emission_area": ("Surface-emission current", "A"),
    "I_displacement_gap": ("Displacement current", "A"),
    "cfl": ("Drift CFL number", ""),
    "diffusion_cfl": ("Diffusion stability number", ""),
    "picard_iterations": ("Picard iterations", ""),
    "adaptive_substeps": ("Adaptive sub-steps", ""),
    "adaptive_dt_sub": ("Sub-step size", "s"),
    "adaptive_cfl_est": ("Pre-step CFL estimate", ""),
    "adaptive_diffusion_cfl_est": ("Pre-step diffusion estimate", ""),
    "ne": ("Electron density nₑ", "m⁻³"),
    "ni": ("Ion density nᵢ", "m⁻³"),
    "phi": ("Potential φ", "V"),
    "E": ("Electric field E", "V/m"),
    "Gamma_e": ("Electron flux Γₑ", "m⁻²s⁻¹"),
    "Gamma_i": ("Ion flux Γᵢ", "m⁻²s⁻¹"),
    "townsend_alpha": ("Townsend α", "m⁻¹"),
    "nu_i": ("Ionization frequency νᵢ", "s⁻¹"),
    "S_ion": ("Ionization source", "m⁻³s⁻¹"),
    "S": ("Net source S", "m⁻³s⁻¹"),
    "mu_e": ("Electron mobility μₑ", "m²/(V·s)"),
    "D_e": ("Electron diffusion Dₑ", "m²/s"),
    "mu_i": ("Ion mobility μᵢ", "m²/(V·s)"),
    "D_i": ("Ion diffusion Dᵢ", "m²/s"),
}


def quantity_label(q: str) -> str:
    return QUANTITY_INFO.get(q, (q, ""))[0]


def quantity_unit(q: str) -> str:
    return QUANTITY_INFO.get(q, (q, ""))[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_UNIT_FROM_SUFFIX = [
    ("_eV", "eV"), ("_K", "K"), ("_deg", "deg"), ("_ps", "ps"), ("_m", "m"), ("_s", "s"),
    ("_J", "J"), ("_Torr", "Torr"),
]
_UNIT_FROM_COMMENT = {
    "[m]": "m", "[s]": "s", "[v]": "V", "[ohm]": "Ω", "[f]": "F", "[h]": "H", "[k]": "K",
    "[hz]": "Hz", "[rad]": "rad", "[torr]": "Torr", "[m^-3]": "m⁻³", "[m^2]": "m²", "[m^3/s]": "m³/s",
}


def humanize(name: str) -> str:
    s = name
    for suf, _ in _UNIT_FROM_SUFFIX:
        if s.endswith(suf):
            s = s[: -len(suf)]
            break
    s = s.replace("_", " ").strip()
    return s[:1].upper() + s[1:]


def emission_param_parts(name: str) -> tuple[str, str] | None:
    """Split ``cathode_laser_U_J`` -> ("cathode", "laser_U_J")."""
    for pre in ("shared_", "anode_", "cathode_"):
        if name.startswith(pre):
            base = name[len(pre):]
            if base in EMISSION_PARAMS:
                return pre[:-1], base
    return None


def meta_for(path: str, comment: str = "") -> Meta:
    if path in FIELD_META:
        return FIELD_META[path]
    name = path.rsplit(".", 1)[-1]
    if path.startswith("emission."):
        parts = emission_param_parts(name)
        if parts:
            who, base = parts
            mech, label, unit, adv = EMISSION_PARAMS[base]
            return Meta(label, unit, adv, section=mech)
        if name.startswith(("anode_enable_", "cathode_enable_")):
            elec, mech = name.split("_enable_", 1)
            mech = mech.replace("_emission", "")
            return Meta(MECH_TITLE.get(mech, humanize(mech)), section=f"{elec}_mechanisms")
    unit = ""
    for suf, u in _UNIT_FROM_SUFFIX:
        if name.endswith(suf):
            unit = u
            break
    low = comment.lower()
    for k, u in _UNIT_FROM_COMMENT.items():
        if k in low:
            unit = unit or u
            break
    return Meta(humanize(name), unit)


def choice_label(value: str) -> str:
    return CHOICE_LABELS.get(str(value), str(value).replace("_", " "))


# ---------------------------------------------------------------------------
# Relevance: which settings matter for the current choices
# ---------------------------------------------------------------------------
def _get(values: dict, path: str, default=None):
    return values.get(path, default)


def electron_tables_in_use(v: dict) -> list[str]:
    used = []
    if v.get("plasma.electron_kinetics_model") == "local_field_approximation" and \
            v.get("local_field_approximation.electron_transport_source") == "swarm_data_table_interpolation":
        used.append("local_field_approximation.electron_swarm_data_path")
    if v.get("plasma.impact_ionization_model") == "from_townsend_alpha" and \
            v.get("townsend_coefficient.townsend_alpha_source_mode") == "interpolate_from_e_over_n_table":
        used.append("townsend_coefficient.townsend_alpha_swarm_data_path")
    if v.get("plasma.impact_ionization_model") == "from_ionization_frequency" and \
            v.get("ionization_frequency_source.ionization_frequency_source_mode") == "interpolate_from_e_over_n_table":
        used.append("ionization_frequency_source.ionization_frequency_swarm_data_path")
    if v.get("emission.use_vaughan_sey") and \
            v.get("emission.vaughan_effective_temperature_mode") == "local_field_approximation":
        if "local_field_approximation.electron_swarm_data_path" not in used:
            used.append("local_field_approximation.electron_swarm_data_path")
    return used


def ion_tables_in_use(v: dict) -> list[str]:
    used = []
    if v.get("plasma.ion_kinetics_model") != "local_field_ion_kinetics":
        return used
    if v.get("ion_transport.mobility_source_mode") == "swarm_data_table_interpolation":
        used.append("ion_transport.mobility_table_path")
    if v.get("ion_transport.diffusion_source_mode") == "swarm_data_table_interpolation":
        used.append("ion_transport.diffusion_table_path")
    return used


def emission_mechanisms(v: dict, electrode: str) -> list[str]:
    if not v.get("emission.enable_external_emission"):
        return []
    if not v.get(f"emission.enable_{electrode}_external_emission"):
        return []
    return [m for m, _ in MECHANISMS if v.get(f"emission.{electrode}_enable_{m}_emission")]


def group_active(group: str, v: dict) -> tuple[bool, str]:
    """Is a whole group relevant for the current settings?"""
    if group == "local_field_approximation":
        ok = v.get("plasma.electron_kinetics_model") == "local_field_approximation" or bool(
            "local_field_approximation.electron_swarm_data_path" in electron_tables_in_use(v))
        return ok, "Used only with Electron kinetics = local-field approximation."
    if group == "electron_swarm_data":
        return bool(electron_tables_in_use(v)), "No electron swarm table is in use."
    if group == "townsend_coefficient":
        return v.get("plasma.impact_ionization_model") == "from_townsend_alpha", \
            "Used only when Impact ionization = from Townsend α."
    if group == "ionization_frequency_source":
        return v.get("plasma.impact_ionization_model") == "from_ionization_frequency", \
            "Used only when Impact ionization = direct ionization frequency."
    if group == "recombination":
        ok = bool(v.get("boundary.enable_volume_sources")) and bool(v.get("boundary.enable_recombination_sink"))
        return ok, "The recombination sink is switched off in Boundary conditions."
    if group == "user_defined_electron_kinetics":
        return False, "This block has no settings."
    return True, ""


def field_active(path: str, v: dict) -> tuple[bool, str]:
    """Is a single setting relevant for the current choices?  Returns (active, why-not)."""
    g, _, name = path.rpartition(".")
    ok, why = group_active(g, v)
    if not ok:
        return ok, why
    if g == "numerics":
        if name == "numba_parallel":
            return v.get("numerics.hotloop_backend") == "numba", "Only for the Numba backend."
        if name in ("target_cfl_substep", "target_diffusion_cfl_substep", "max_substeps",
                    "adaptive_substep_overflow_policy", "adaptive_substep_warn_every"):
            return bool(v.get("numerics.use_adaptive_substepping")), "Adaptive sub-stepping is off."
    if g == "geometry" and name == "eps_r":
        return float(v.get("geometry.l") or 0) > 0, "Only with a dielectric layer (l > 0)."
    if g == "local_field_approximation" and name == "electron_swarm_data_path":
        return path in electron_tables_in_use(v), "The LFA source is a user-defined equation."
    if g == "townsend_coefficient" and name == "townsend_alpha_swarm_data_path":
        return path in electron_tables_in_use(v), "α comes from the user-defined equation."
    if g == "ionization_frequency_source" and name == "ionization_frequency_swarm_data_path":
        return path in electron_tables_in_use(v), "νᵢ comes from the user-defined equation."
    if g == "ion_transport":
        local = v.get("plasma.ion_kinetics_model") == "local_field_ion_kinetics"
        if name in ("mobility_source_mode", "diffusion_source_mode"):
            return local, "Only with Ion kinetics = local-field ion kinetics."
        if name in ("mobility_table_path", "diffusion_table_path"):
            return path in ion_tables_in_use(v), "This table is not selected as a source."
        if name in ("out_of_range_policy", "gas_temperature_tolerance_K"):
            return bool(ion_tables_in_use(v)), "No ion table is in use."
    if g == "waveform":
        wt = v.get("waveform.waveform_type")
        need = {
            "step": {"V_peak", "tV_start", "tV_end"},
            "gaussian": {"V_peak", "t_peak", "tau"},
            "dc": {"V_peak"},
            "rf": {"V_peak", "f_rf", "V_dc", "phi_rf"},
        }.get(wt)
        if name == "waveform_type":
            return True, ""
        if need is None:  # table types
            return name.startswith("table_"), "Not used by a tabulated waveform."
        return name in need, f"Not used by the '{wt}' waveform."
    if g == "boundary" and name in ("enable_ionization_source", "enable_recombination_sink"):
        return bool(v.get("boundary.enable_volume_sources")), "All volume sources are off."
    if g == "circuit":
        if name in ("circuit_type", "circuit_time_scheme"):
            return True, ""
        els = TOPOLOGY_ELEMENTS.get(v.get("circuit.circuit_type"), [])
        return name in els, "Not part of the selected topology."
    if g == "diagnostics.averaged_spatial":
        mode = v.get("diagnostics.averaged_spatial.mode")
        if name in ("t_avg_start", "t_avg_end"):
            return mode == "time_window", "Only for the time-window mode."
        if name == "N_cycle_avg":
            return mode == "last_n_cycles", "Only for the last-N-cycles mode."
    if g == "emission":
        return _emission_field_active(name, v)
    return True, ""


def _emission_field_active(name: str, v: dict) -> tuple[bool, str]:
    if name.startswith("vaughan_"):
        return bool(v.get("emission.use_vaughan_sey")), "The Vaughan model is off."
    if name in ("anode_electron_induced_yield",):
        return not v.get("emission.use_vaughan_sey"), "Replaced by the Vaughan model."
    ext = bool(v.get("emission.enable_external_emission"))
    if name in ("electrode_material_mode", "enable_anode_external_emission", "enable_cathode_external_emission"):
        return ext, "External emission is switched off."
    if name.startswith(("anode_enable_", "cathode_enable_")):
        elec = name.split("_", 1)[0]
        return ext and bool(v.get(f"emission.enable_{elec}_external_emission")), \
            f"The {elec} does not emit."
    parts = emission_param_parts(name)
    if parts:
        who, base = parts
        mech = EMISSION_PARAMS[base][0]
        shared = v.get("emission.electrode_material_mode", "shared") == "shared"
        if who == "shared":
            if not shared:
                return False, "Material mode is 'separate'."
            used = mech in emission_mechanisms(v, "anode") or mech in emission_mechanisms(v, "cathode")
            return used, "This mechanism is not enabled on any electrode."
        if shared:
            return False, "Material mode is 'shared' (shared_* parameters are used)."
        return mech in emission_mechanisms(v, who), f"Not enabled on the {who}."
    return True, ""


# ---------------------------------------------------------------------------
# Form layout
# ---------------------------------------------------------------------------
@dataclass
class Section:
    key: str
    title: str
    paths: list[str] = field(default_factory=list)
    note: str = ""


def group_sections(group: str, field_paths: list[str], values: dict, comments: dict[str, str]) -> list[Section]:
    """Split the fields of a group into titled sections, in display order."""
    if group == "emission":
        return _emission_sections(field_paths, values)
    order: list[str] = []
    secs: dict[str, Section] = {}
    for p in field_paths:
        meta = meta_for(p, comments.get(p, ""))
        key = meta.section or "General"
        if key not in secs:
            secs[key] = Section(key=key, title=key if key != "General" else "")
            order.append(key)
        secs[key].paths.append(p)
    return [secs[k] for k in order]


def _emission_sections(field_paths: list[str], v: dict) -> list[Section]:
    names = {p.split(".", 1)[1]: p for p in field_paths}
    secs = [
        Section("see", "Secondary electron emission",
                [names[n] for n in ("gamma", "use_vaughan_sey", "anode_electron_induced_yield") if n in names]),
        Section("vaughan", "Vaughan model", [p for n, p in names.items() if n.startswith("vaughan_")]),
        Section("ext", "External emission",
                [names[n] for n in ("enable_external_emission", "enable_cathode_external_emission",
                                    "enable_anode_external_emission", "electrode_material_mode") if n in names]),
        Section("cathode_mechanisms", "Cathode mechanisms",
                [p for n, p in names.items() if n.startswith("cathode_enable_")]),
        Section("anode_mechanisms", "Anode mechanisms",
                [p for n, p in names.items() if n.startswith("anode_enable_")]),
    ]
    for mech, title in MECHANISMS:
        for who in ("shared", "cathode", "anode"):
            ps = [p for n, p in names.items()
                  if (pp := emission_param_parts(n)) and pp[0] == who and EMISSION_PARAMS[pp[1]][0] == mech]
            order = list(EMISSION_PARAMS)
            ps.sort(key=lambda p: order.index(emission_param_parts(p.split(".", 1)[1])[1]))
            if not ps:
                continue
            ttl = f"{title}" + ("" if who == "shared" else f" — {who}")
            secs.append(Section(f"{mech}:{who}", ttl, ps))
    known = {p for s in secs for p in s.paths}
    rest = [p for p in field_paths if p not in known]
    if rest:
        secs.append(Section("other", "Other", rest))
    return secs


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def search_text(path: str, comment: str) -> str:
    meta = meta_for(path, comment)
    g = path.rpartition(".")[0]
    return " ".join([path, meta.label, GROUP_TITLES.get(g, g), comment, meta.unit]).lower()


def match_score(query: str, text: str) -> float:
    q = query.lower().strip()
    if not q:
        return 0.0
    if q in text:
        return 2.0 + (1.0 if text.startswith(q) else 0.0)
    words = [w for w in re.split(r"\s+", q) if w]
    hits = sum(1 for w in words if w in text)
    return hits / max(len(words), 1)
