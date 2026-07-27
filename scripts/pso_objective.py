"""PSO objective function J and scenario generation.

Implements the multi-objective cost function defined in the V3.2 thesis design
(Section 5.6)::

    J = 0.45 * NEC_IAE + 0.20 * NEC_overshoot
      + 0.15 * pH_band_violation + 0.10 * control_TV
      + 0.10 * saturation + P

All components are normalised against the fixed-PI (C0) baseline for the same
scenario, making J dimensionless and comparable across working points.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np
import yaml

from plc_control.gain_schedule import load_gain_schedule


# ---------------------------------------------------------------------------
# Scenario definition
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    """A single simulation scenario with perturbations applied to the model."""

    point_id: str          # "low" / "medium" / "high"
    disturbance: str        # "S0_nominal" / "S1_qw_up" / ...
    gain_point: dict        # Working-point dict from gain_schedule

    # Perturbation multipliers (1.0 = nominal)
    q_w_factor: float = 1.0
    npk_conc_factor: float = 1.0
    acid_ph_offset: float = 0.0
    pipe_delay_factor: float = 1.0
    soil_fc_factor: float = 1.0
    ec_noise_std: float = 0.0
    ph_noise_std: float = 0.0


# ---------------------------------------------------------------------------
# Scene generation
# ---------------------------------------------------------------------------


def generate_training_scenarios(
    gain_schedule_path: str | Path | None = None,
) -> list[Scenario]:
    """Generate 12 training scenarios for the medium working point.

    The full 24 scenarios for 3 working points would be generated in the
    multi-seed outer loop, but PSO training uses only ``medium`` for speed.
    Low and high are reserved for generalisation testing.

    Returns a balanced mix of nominal and perturbed scenarios.
    """
    gain_cfg = load_gain_schedule(
        gain_schedule_path or "config/gain_schedule.yaml"
    )
    points = []
    for stage_name, stage_data in gain_cfg.get("stages", {}).items():
        for pt in stage_data.get("points", []):
            if pt.get("valid", False):
                points.append(pt)

    if not points:
        raise ValueError("No valid gain points found in gain schedule")

    # Use medium for training
    medium_pts = [p for p in points if p.get("id") == "medium"]
    if not medium_pts:
        medium_pts = [points[0]]  # fallback: use first valid point

    pt = medium_pts[0]
    scenarios: list[Scenario] = []

    # S0: Nominal
    scenarios.append(Scenario("medium", "S0_nominal", pt))

    # S1: q_w perturbations
    for factor, label in [(1.1, "S1_qw_up"), (0.9, "S1_qw_down")]:
        scenarios.append(Scenario("medium", label, pt, q_w_factor=factor))

    # S2: NPK concentration perturbations
    for factor, label in [(1.1, "S2_npk_up"), (0.9, "S2_npk_down")]:
        scenarios.append(Scenario("medium", label, pt, npk_conc_factor=factor))

    # S3: Acid pH perturbations
    for offset, label in [(0.2, "S3_acid_ph_up"), (-0.2, "S3_acid_ph_down")]:
        scenarios.append(Scenario("medium", label, pt, acid_ph_offset=offset))

    # S4: Pipe delay perturbations
    for factor, label in [(1.2, "S4_delay_up"), (0.8, "S4_delay_down")]:
        scenarios.append(Scenario("medium", label, pt, pipe_delay_factor=factor))

    # S5: Soil FC perturbation
    for factor, label in [(1.1, "S5_fc_up"), (0.9, "S5_fc_down")]:
        scenarios.append(Scenario("medium", label, pt, soil_fc_factor=factor))

    # S6: Measurement noise
    scenarios.append(Scenario("medium", "S6_noise", pt,
                               ec_noise_std=0.02, ph_noise_std=0.05))

    # S7: Joint perturbation (one representative)
    scenarios.append(Scenario(
        "medium", "S7_joint", pt,
        q_w_factor=1.05, npk_conc_factor=0.95, acid_ph_offset=0.1,
        pipe_delay_factor=1.1, soil_fc_factor=0.95,
        ec_noise_std=0.01, ph_noise_std=0.03,
    ))

    return scenarios


def generate_test_scenarios(
    gain_schedule_path: str | Path | None = None,
    n_total: int = 100,
) -> list[Scenario]:
    """Generate diverse test scenarios with random perturbation sampling."""
    gain_cfg = load_gain_schedule(
        gain_schedule_path or "config/gain_schedule.yaml"
    )
    points = []
    for stage_data in gain_cfg.get("stages", {}).values():
        for pt in stage_data.get("points", []):
            if pt.get("valid", False):
                points.append(pt)

    rng = np.random.default_rng(42)
    scenarios: list[Scenario] = []
    for i in range(n_total):
        pt = points[i % len(points)]
        s = Scenario(
            point_id=str(pt.get("id", "unknown")),
            disturbance=f"test_{i:03d}",
            gain_point=pt,
            q_w_factor=float(rng.uniform(0.85, 1.15)),
            npk_conc_factor=float(rng.uniform(0.85, 1.15)),
            acid_ph_offset=float(rng.uniform(-0.3, 0.3)),
            pipe_delay_factor=float(rng.uniform(0.75, 1.25)),
            soil_fc_factor=float(rng.uniform(0.85, 1.15)),
            ec_noise_std=float(rng.uniform(0.0, 0.03)),
            ph_noise_std=float(rng.uniform(0.0, 0.08)),
        )
        scenarios.append(s)
    return scenarios


# ---------------------------------------------------------------------------
# Cost function J
# ---------------------------------------------------------------------------


@dataclass
class JWeights:
    w_iae: float = 0.45
    w_overshoot: float = 0.20
    w_ph_band: float = 0.15
    w_tv: float = 0.10
    w_saturation: float = 0.10


@dataclass
class BaselineMetrics:
    """C0 (fixed PI, no decoupling) baseline for normalisation."""
    ec_iae: float = 0.1
    ec_overshoot: float = 0.05
    ph_band_violation_integral: float = 0.1
    control_tv: float = 0.1
    saturation_fraction: float = 0.01


def compute_J(results: list[dict], baseline: BaselineMetrics | None = None,
              weights: JWeights | None = None) -> tuple[float, dict, bool]:
    """Compute the scalar cost J from a list of per-step info dicts.

    Parameters
    ----------
    results : list of dict
        Per-step ``info`` dicts from ``PIDControlledTwinEnv.step()``.
    baseline : BaselineMetrics, optional
        Pre-computed C0 baseline for normalisation.  If None, no normalisation.
    weights : JWeights, optional
        Weight coefficients (default from V3.2).

    Returns
    -------
    J : float
        Scalar cost (lower is better).  ``inf`` if infeasible.
    breakdown : dict
        Individual component values (unnormalised).
    feasible : bool
        Whether hard constraints are satisfied.
    """
    if weights is None:
        weights = JWeights()
    if baseline is None:
        baseline = BaselineMetrics()

    if not results:
        return float("inf"), {}, False

    # Extract time-series
    n = len(results)
    ec_set = np.array([r.get("ec_set", 0.0) for r in results])
    ec_actual = np.array([r.get("ec_drip", 0.0) for r in results])
    ph_actual = np.array([r.get("ph_drip", 7.0) for r in results])
    q_f = np.array([r.get("q_f", 0.0) for r in results])
    q_a = np.array([r.get("q_a", 0.0) for r in results])
    water_flow_ok = np.array([r.get("water_flow_ok", True) for r in results])

    # ---- Hard constraints (infeasibility checks) ----
    ph_low = 5.5
    if np.any(ph_actual < ph_low):
        return float("inf"), {}, False

    # No dosing when water flow is lost
    dosing_when_no_flow = np.any((q_f > 1e-6) & ~water_flow_ok)
    dosing_when_no_flow |= np.any((q_a > 1e-6) & ~water_flow_ok)
    if dosing_when_no_flow:
        return float("inf"), {}, False

    # ---- EC IAE ----
    ec_error = np.abs(ec_actual - ec_set)
    # Approximate dt from the number of steps (typical: dt_min minutes)
    # We don't have dt per step in the info dict, so use step count proxy
    ec_iae = np.sum(ec_error) / max(n, 1)

    # ---- EC overshoot ----
    overshoot = np.maximum(ec_actual - ec_set, 0.0)
    ec_overshoot = np.max(overshoot) if len(overshoot) > 0 else 0.0

    # ---- pH band violation integral ----
    ph_lower = 5.8
    ph_upper = 6.5
    ph_violation = np.where(
        ph_actual < ph_lower,
        ph_lower - ph_actual,
        np.where(ph_actual > ph_upper, ph_actual - ph_upper, 0.0),
    )
    ph_violation_integral = np.sum(ph_violation) / max(n, 1)

    # ---- Control total variation ----
    dq_f = np.diff(q_f, prepend=q_f[0])
    dq_a = np.diff(q_a, prepend=q_a[0])
    control_tv = np.sum(np.abs(dq_f) + np.abs(dq_a)) / max(n, 1)

    # ---- Saturation fraction ----
    q_f_max_est = np.max(q_f) if np.max(q_f) > 0 else 10.0
    q_a_max_est = np.max(q_a) if np.max(q_a) > 0 else 4.0
    saturated = (q_f >= 0.99 * q_f_max_est) | (q_a >= 0.99 * q_a_max_est)
    sat_frac = np.mean(saturated.astype(float))

    # ---- Normalise against baseline ----
    nec_iae = ec_iae / max(baseline.ec_iae, 1e-9)
    nec_overshoot = ec_overshoot / max(baseline.ec_overshoot, 1e-9)
    n_ph = ph_violation_integral / max(baseline.ph_band_violation_integral, 1e-9)
    n_tv = control_tv / max(baseline.control_tv, 1e-9)
    n_sat = sat_frac / max(baseline.saturation_fraction, 1e-9)

    # ---- Weighted sum ----
    J = (
        weights.w_iae * nec_iae
        + weights.w_overshoot * nec_overshoot
        + weights.w_ph_band * n_ph
        + weights.w_tv * n_tv
        + weights.w_saturation * n_sat
    )

    breakdown = {
        "ec_iae": ec_iae,
        "ec_overshoot": ec_overshoot,
        "ph_violation_integral": ph_violation_integral,
        "control_tv": control_tv,
        "saturation_fraction": sat_frac,
        "nec_iae": nec_iae,
        "nec_overshoot": nec_overshoot,
        "n_ph_band": n_ph,
        "n_tv": n_tv,
        "n_saturation": n_sat,
        "J": J,
    }

    return J, breakdown, True


# ---------------------------------------------------------------------------
# Single-particle evaluation (runs PIDControlledTwinEnv per scenario)
# ---------------------------------------------------------------------------


def evaluate_particle(
    x: np.ndarray,
    scenarios: list[Scenario],
    baseline: BaselineMetrics,
    weights: JWeights | None = None,
    ep_len_days: float = 1.0,
    dt_min: float = 10.0,
    verbose: bool = False,
) -> float:
    """Run one particle across all training scenarios and return aggregate J.

    Parameters
    ----------
    x : np.ndarray
        [lambda_EC_s, lambda_pH_s, beta]
    scenarios : list of Scenario
        Scenarios to evaluate.
    baseline : BaselineMetrics
        C0 baseline metrics for normalisation.
    ep_len_days : float
        Simulation duration per scenario (days).
    dt_min : float
        Simulation step (minutes).
    verbose : bool
        Print per-scenario progress.

    Returns
    -------
    float
        Mean J across scenarios, or ``inf`` if any scenario is infeasible.
    """
    from scripts.pso_env import PIDControlledTwinEnv

    lambda_ec, lambda_ph, beta = float(x[0]), float(x[1]), float(x[2])
    total_J = 0.0

    for scenario in scenarios:
        try:
            env = PIDControlledTwinEnv(
                lambda_ec_s=lambda_ec,
                lambda_ph_s=lambda_ph,
                beta=beta,
                gain_point=scenario.gain_point,
                ep_len_days=ep_len_days,
                dt_min=dt_min,
                q_w=scenario.gain_point.get("q_f", 4.0),
                soil_model="lumped_v1",
                seed=None,
            )

            # Apply scenario perturbations
            _apply_scenario_perturbations(env, scenario)

            obs = env.reset()
            results = []
            done = False

            while not done:
                # Fixed action: nominal water + zero EC residual (setpoint tracking)
                action = np.array([1.0 / scenario.q_w_factor, 0.0], dtype=np.float32)
                obs, reward, done, info = env.step(action)
                # Inject measurement noise in the observation
                if scenario.ec_noise_std > 0 or scenario.ph_noise_std > 0:
                    info_copy = dict(info)
                    info_copy["ec_drip"] += np.random.normal(0, scenario.ec_noise_std)
                    info_copy["ph_drip"] += np.random.normal(0, scenario.ph_noise_std)
                    results.append(info_copy)
                else:
                    results.append(info)

            J, breakdown, feasible = compute_J(results, baseline, weights)

            if not feasible:
                if verbose:
                    print(f"  [{scenario.disturbance}] INFEASIBLE (pH_min={min(r.get('ph_drip', 7) for r in results):.2f})")
                return float("inf")

            total_J += J
        except (ValueError, AttributeError, RuntimeError) as e:
            if verbose:
                print(f"  [{scenario.disturbance}] ERROR: {e}")
            return float("inf")

    mean_J = total_J / max(len(scenarios), 1)
    return mean_J


def _apply_scenario_perturbations(env, scenario: Scenario):
    """Apply perturbation factors to the environment's model parameters."""
    # Water flow perturbation
    if scenario.q_w_factor != 1.0:
        env._base_q_w *= scenario.q_w_factor
        env.water_pump.q_set_l_min = env._base_q_w

    # NPK concentration perturbation
    if scenario.npk_conc_factor != 1.0:
        env.tank.ec_conc *= scenario.npk_conc_factor

    # Acid pH perturbation
    if scenario.acid_ph_offset != 0.0:
        env.tank.ph_acid = max(1.0, min(6.0, env.tank.ph_acid + scenario.acid_ph_offset))

    # Pipe delay perturbation (modify tau as a proxy for delay changes)
    if scenario.pipe_delay_factor != 1.0:
        env.pipe.tau = max(1.0, env.pipe.tau * scenario.pipe_delay_factor)

    # Soil FC perturbation
    if scenario.soil_fc_factor != 1.0:
        try:
            if hasattr(env.soil, "theta_fc"):
                env.soil.theta_fc *= scenario.soil_fc_factor
        except (AttributeError, TypeError):
            pass  # theta_fc may be a read-only property in some soil models


def compute_baseline(
    scenarios: list[Scenario],
    ep_len_days: float = 1.0,
    dt_min: float = 10.0,
) -> BaselineMetrics:
    """Compute C0 baseline metrics (fixed PI, no decoupling) across scenarios.

    Uses a conservative lambda (large = slow) to approximate fixed PI behaviour.
    """
    all_ec_iae: list[float] = []
    all_ec_overshoot: list[float] = []
    all_ph_viol: list[float] = []
    all_tv: list[float] = []
    all_sat: list[float] = []

    for scenario in scenarios:
        try:
            from scripts.pso_env import PIDControlledTwinEnv

            env = PIDControlledTwinEnv(
                lambda_ec_s=600.0,   # Very slow → approximates weak PI
                lambda_ph_s=900.0,   # Very slow → approximates weak PI
                beta=0.0,
                gain_point=scenario.gain_point,
                ep_len_days=ep_len_days,
                dt_min=dt_min,
                q_w=scenario.gain_point.get("q_f", 4.0),
                soil_model="lumped_v1",
                seed=None,
            )
            obs = env.reset()
            results = []
            done = False
            while not done:
                action = np.array([1.0, 0.0], dtype=np.float32)
                obs, reward, done, info = env.step(action)
                results.append(info)

            _, breakdown, feasible = compute_J(
                results, baseline=BaselineMetrics(), weights=JWeights(
                    w_iae=1.0, w_overshoot=1.0, w_ph_band=1.0, w_tv=1.0, w_saturation=1.0,
                )
            )
            if feasible:
                all_ec_iae.append(breakdown["ec_iae"])
                all_ec_overshoot.append(breakdown["ec_overshoot"])
                all_ph_viol.append(breakdown["ph_violation_integral"])
                all_tv.append(breakdown["control_tv"])
                all_sat.append(breakdown["saturation_fraction"])
        except Exception:
            continue

    if not all_ec_iae:
        return BaselineMetrics()

    return BaselineMetrics(
        ec_iae=max(np.mean(all_ec_iae), 1e-6),
        ec_overshoot=max(np.mean(all_ec_overshoot), 1e-6),
        ph_band_violation_integral=max(np.mean(all_ph_viol), 1e-6),
        control_tv=max(np.mean(all_tv), 1e-6),
        saturation_fraction=max(np.mean(all_sat), 1e-6),
    )
