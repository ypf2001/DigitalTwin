"""PSO offline IMC parameter tuning — main entry point.

Implements the V3.2 PSO workflow:

    1. Load identified gain schedule.
    2. Generate training scenarios.
    3. Compute C0 baseline for normalisation.
    4. Run 20 independent PSO seeds.
    5. Select the best feasible solution.
    6. Compute PID parameters via IMC formula.
    7. Save locked_controller.yaml + CSV outputs.

Usage::

    python scripts/pso_optimizer.py [--seeds 20] [--quick]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

# Ensure project root is on path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scripts.pso_core import PSO, PSOResult
from scripts.pso_objective import (
    BaselineMetrics,
    JWeights,
    Scenario,
    compute_baseline,
    evaluate_particle,
    generate_training_scenarios,
    generate_test_scenarios,
)
from plc_control.imc_smith import FOPDTModel, tune_imc_pi
from plc_control.gain_schedule import load_gain_schedule


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _save_seed_csv(results_dir: Path, seed: int, result: PSOResult):
    """Save convergence data for one seed."""
    path = results_dir / f"convergence_seed_{seed:02d}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("generation,best_cost,mean_cost\n")
        for gen, (best, mean) in enumerate(zip(result.convergence, result.mean_costs)):
            f.write(f"{gen},{best:.6f},{mean:.6f}\n")


def _save_summary_csv(results_dir: Path, seed_results: list[dict]):
    """Save the per-seed summary."""
    path = results_dir / "pso_runs.csv"
    with open(path, "w", encoding="utf-8") as f:
        f.write("seed,lambda_ec_s,lambda_ph_s,beta,J_train,feasible,generations,"
                "early_stopped,elapsed_s,kp_ec,ki_ec,kp_ph,ki_ph\n")
        for r in seed_results:
            f.write(
                f"{r['seed']},{r['lambda_ec']:.2f},{r['lambda_ph']:.2f},"
                f"{r['beta']:.4f},{r['J']:.6f},{r['feasible']},"
                f"{r['generations']},{r['early_stopped']},{r['elapsed_s']:.1f},"
                f"{r.get('kp_ec', 0):.4f},{r.get('ki_ec', 0):.6f},"
                f"{r.get('kp_ph', 0):.4f},{r.get('ki_ph', 0):.6f}\n"
            )


def _save_locked_controller(results_dir: Path, best: dict, gain_point: dict):
    """Save the final locked controller parameters as YAML and JSON."""
    timestamp = datetime.now(timezone.utc).isoformat()

    ec_model = FOPDTModel(
        gain=float(gain_point["gains"]["g_ec_f"]),
        tau_s=float(gain_point.get("tau_s", 375.0)),
        delay_s=float(gain_point.get("delay_s", 185.0)),
    )
    ph_model = FOPDTModel(
        gain=float(gain_point["gains"]["g_ph_a"]),
        tau_s=float(gain_point.get("tau_s", 375.0)),
        delay_s=float(gain_point.get("delay_s", 185.0)),
    )
    ec_pid = tune_imc_pi(ec_model, lambda_s=best["lambda_ec"])
    ph_pid = tune_imc_pi(ph_model, lambda_s=best["lambda_ph"])

    config_str = json.dumps(best, sort_keys=True)
    config_hash = hashlib.sha256(config_str.encode()).hexdigest()[:12]

    locked = {
        "version": "1.0",
        "timestamp": timestamp,
        "seed": best["seed"],
        "lambda_ec_s": best["lambda_ec"],
        "lambda_ph_s": best["lambda_ph"],
        "beta": best["beta"],
        "J_train": best["J"],
        "pid": {
            "ec": {"kp": ec_pid.kp, "ki_per_s": ec_pid.ki_per_s,
                   "integral_time_s": ec_pid.integral_time_s},
            "ph": {"kp": ph_pid.kp, "ki_per_s": ph_pid.ki_per_s,
                   "integral_time_s": ph_pid.integral_time_s},
        },
        "hashes": {"config_sha256": config_hash},
    }

    # YAML
    yaml_path = results_dir / "locked_controller.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(locked, f, default_flow_style=False, sort_keys=False)

    # JSON metadata
    json_path = results_dir / "locked_controller_meta.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(locked, f, indent=2)

    return locked


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="PSO offline IMC tuning")
    parser.add_argument("--seeds", type=int, default=20,
                        help="Number of independent PSO seeds (default: 20)")
    parser.add_argument("--quick", action="store_true",
                        help="Quick test: 5 particles, 10 gens, 3 seeds")
    parser.add_argument("--output", type=str, default="results/optimization",
                        help="Output directory (default: results/optimization)")
    parser.add_argument("--gain-schedule", type=str,
                        default="config/gain_schedule.yaml",
                        help="Path to gain schedule YAML")
    parser.add_argument("--ep-len-days", type=float, default=1.0,
                        help="Episode length in days (default: 1.0)")
    parser.add_argument("--dt-min", type=float, default=10.0,
                        help="Simulation step in minutes (default: 10)")
    args = parser.parse_args()

    # Quick mode override
    n_seeds = 3 if args.quick else args.seeds
    n_particles = 5 if args.quick else 30
    max_iter = 10 if args.quick else 100
    patience = 5 if args.quick else 20

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"{'='*60}")
    print(f"PSO Offline IMC Tuning (V3.2)")
    print(f"{'='*60}")
    print(f"  Seeds:  {n_seeds}  |  Particles: {n_particles}  |  Max gens: {max_iter}")
    print(f"  Output: {output_dir}")
    print(f"{'='*60}\n")

    # ---- 1. Load gain schedule ----
    gain_cfg = load_gain_schedule(args.gain_schedule)
    medium_pt = _find_medium_point(gain_cfg)

    delay_s = float(medium_pt.get("delay_s", 185.0))
    tau_s = float(medium_pt.get("tau_s", 375.0))

    # Search bounds per V3.2 Section 5.4
    bounds = [
        (max(float(medium_pt.get("delay_s", 30.0)), 30.0), 600.0),  # lambda_EC
        (max(float(medium_pt.get("delay_s", 30.0)), 30.0), 900.0),  # lambda_pH
        (0.0, 0.5),                                                    # beta
    ]

    print(f"Search bounds: lambda_EC ∈ [{bounds[0][0]:.0f}, {bounds[0][1]:.0f}] s")
    print(f"               lambda_pH ∈ [{bounds[1][0]:.0f}, {bounds[1][1]:.0f}] s")
    print(f"               beta     ∈ [{bounds[2][0]:.1f}, {bounds[2][1]:.1f}]")
    print(f"Gain point:   medium (EC={medium_pt['ec']}, pH={medium_pt['ph']})")
    print()

    # ---- 2. Generate scenarios ----
    print("Generating training scenarios...")
    train_scenarios = generate_training_scenarios(args.gain_schedule)
    print(f"  Training scenarios: {len(train_scenarios)}")
    test_scenarios = generate_test_scenarios(args.gain_schedule, n_total=100)
    print(f"  Test scenarios:     {len(test_scenarios)}")
    print()

    # ---- 3. Compute baseline ----
    print("Computing C0 baseline (lambda=600/900, beta=0)...")
    t0 = time.perf_counter()
    baseline = compute_baseline(
        train_scenarios,
        ep_len_days=args.ep_len_days,
        dt_min=args.dt_min,
    )
    print(f"  Baseline IAE:        {baseline.ec_iae:.4f}")
    print(f"  Baseline overshoot:  {baseline.ec_overshoot:.4f}")
    print(f"  Baseline pH viol:    {baseline.ph_band_violation_integral:.4f}")
    print(f"  Baseline TV:         {baseline.control_tv:.4f}")
    print(f"  Baseline sat:        {baseline.saturation_fraction:.4f}")
    print(f"  Elapsed: {time.perf_counter() - t0:.1f}s\n")

    # ---- 4. Run PSO seeds ----
    weights = JWeights()
    seed_results: list[dict] = []

    for seed in range(n_seeds):
        print(f"--- Seed {seed+1}/{n_seeds} ---")

        def objective(x):
            return evaluate_particle(
                x, train_scenarios, baseline, weights,
                ep_len_days=args.ep_len_days, dt_min=args.dt_min,
            )

        pso = PSO(
            bounds=bounds,
            n_particles=n_particles,
            max_iter=max_iter,
            patience=patience,
            seed=seed,
        )

        t_seed = time.perf_counter()
        result = pso.optimize(objective)
        elapsed = time.perf_counter() - t_seed

        feasible = not np.isinf(result.best_cost)

        # Compute PID from best lambda
        ec_m = FOPDTModel(float(medium_pt["gains"]["g_ec_f"]), tau_s, delay_s)
        ph_m = FOPDTModel(float(medium_pt["gains"]["g_ph_a"]), tau_s, delay_s)
        ec_pid = tune_imc_pi(ec_m, lambda_s=result.best_position[0])
        ph_pid = tune_imc_pi(ph_m, lambda_s=result.best_position[1])

        seed_info = {
            "seed": seed,
            "lambda_ec": float(result.best_position[0]),
            "lambda_ph": float(result.best_position[1]),
            "beta": float(result.best_position[2]),
            "J": float(result.best_cost),
            "feasible": feasible,
            "generations": result.generations,
            "early_stopped": result.early_stopped,
            "elapsed_s": elapsed,
            "kp_ec": ec_pid.kp,
            "ki_ec": ec_pid.ki_per_s,
            "kp_ph": ph_pid.kp,
            "ki_ph": ph_pid.ki_per_s,
        }
        seed_results.append(seed_info)
        _save_seed_csv(output_dir, seed, result)

        print(f"  Best: λ_EC={result.best_position[0]:.1f}s  "
              f"λ_pH={result.best_position[1]:.1f}s  "
              f"β={result.best_position[2]:.3f}  "
              f"J={result.best_cost:.4f}  "
              f"feasible={feasible}  "
              f"gens={result.generations}  "
              f"time={elapsed:.0f}s")

        if feasible and result.convergence:
            print(f"  Convergence: {result.convergence[0]:.4f} → {result.convergence[-1]:.4f}")

    # ---- 5. Select best feasible ----
    feasible_results = [r for r in seed_results if r["feasible"]]
    print(f"\n{'='*60}")
    print(f"Feasible seeds: {len(feasible_results)}/{n_seeds}")
    if feasible_results:
        best = min(feasible_results, key=lambda r: r["J"])
        print(f"Best:  seed={best['seed']}  λ_EC={best['lambda_ec']:.1f}s  "
              f"λ_pH={best['lambda_ph']:.1f}s  β={best['beta']:.3f}  "
              f"J={best['J']:.4f}")

        # ---- 6. Save outputs ----
        _save_summary_csv(output_dir, seed_results)
        locked = _save_locked_controller(output_dir, best, medium_pt)

        print(f"\nSaved locked_controller.yaml:")
        print(f"  λ_EC = {locked['lambda_ec_s']:.1f} s  →  "
              f"Kp={locked['pid']['ec']['kp']:.4f}  Ki={locked['pid']['ec']['ki_per_s']:.6f}")
        print(f"  λ_pH = {locked['lambda_ph_s']:.1f} s  →  "
              f"Kp={locked['pid']['ph']['kp']:.4f}  Ki={locked['pid']['ph']['ki_per_s']:.6f}")
        print(f"  β    = {locked['beta']:.3f}")
    else:
        print("WARNING: No feasible solution found!")

    print(f"\nOutputs in: {output_dir.resolve()}")
    print("Done.")


def _find_medium_point(gain_cfg: dict) -> dict:
    """Extract the medium working point from the gain schedule."""
    for stage_data in gain_cfg.get("stages", {}).values():
        for pt in stage_data.get("points", []):
            if pt.get("id") == "medium" and pt.get("valid", False):
                return pt
    # Fallback: first valid point
    for stage_data in gain_cfg.get("stages", {}).values():
        for pt in stage_data.get("points", []):
            if pt.get("valid", False):
                return pt
    raise ValueError("No valid gain points in schedule")


if __name__ == "__main__":
    main()
