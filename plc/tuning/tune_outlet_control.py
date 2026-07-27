"""Auto-tune PLC outlet EC/pH control against deployment acceptance targets.

This script tunes only the outlet loop:

    PLC q_f/q_a -> mixing tank + pipe -> outlet EC/pH feedback

It does not use the field/root-zone model. The acceptance targets are the
pre-field requirements before connecting the controller to soil or SAC.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.run_plc_setpoint_step import run as run_step_test
from plc.tools.deployment_preflight import _connect_plc


@dataclass(frozen=True)
class Candidate:
    kp_ec: float
    ki_ec: float
    kd_ec: float
    kp_ph: float
    ki_ph: float
    kd_ph: float
    ec_trim_band: float
    ph_trim_band: float


TARGETS = {
    "ec_tail_mae": 0.03,
    "ph_tail_mae": 0.05,
    "ec_final_abs": 0.05,
    "ph_final_abs": 0.08,
    "ph_tail_drop": 0.02,
}


def _score(metrics: dict[str, float], ec_set: float, ph_set: float) -> float:
    ec_final_abs = abs(float(metrics["ec_final"]) - ec_set)
    ph_final_abs = abs(float(metrics["ph_final"]) - ph_set)
    score = 0.0
    score += float(metrics["ec_tail_mae"]) / TARGETS["ec_tail_mae"]
    score += float(metrics["ph_tail_mae"]) / TARGETS["ph_tail_mae"]
    score += ec_final_abs / TARGETS["ec_final_abs"]
    score += ph_final_abs / TARGETS["ph_final_abs"]
    score += max(float(metrics["ph_tail_drop"]), 0.0) / TARGETS["ph_tail_drop"]
    # Strongly penalize the exact failure mode: pH below target and still falling.
    if float(metrics["ph_final"]) < ph_set and float(metrics["ph_tail_drop"]) > 0.0:
        score += 5.0
    return score


def _passed(metrics: dict[str, float], ec_set: float, ph_set: float) -> bool:
    return (
        float(metrics["ec_tail_mae"]) <= TARGETS["ec_tail_mae"]
        and float(metrics["ph_tail_mae"]) <= TARGETS["ph_tail_mae"]
        and abs(float(metrics["ec_final"]) - ec_set) <= TARGETS["ec_final_abs"]
        and abs(float(metrics["ph_final"]) - ph_set) <= TARGETS["ph_final_abs"]
        and float(metrics["ph_tail_drop"]) <= TARGETS["ph_tail_drop"]
    )


def _candidate_grid(args: argparse.Namespace) -> list[Candidate]:
    base = Candidate(
        kp_ec=args.base_kp_ec,
        ki_ec=args.base_ki_ec,
        kd_ec=args.base_kd_ec,
        kp_ph=args.base_kp_ph,
        ki_ph=args.base_ki_ph,
        kd_ph=args.base_kd_ph,
        ec_trim_band=args.base_ec_trim_band,
        ph_trim_band=args.base_ph_trim_band,
    )
    candidates = [base]

    # Conservative sweep: EC is mostly feedforward; pH is more sensitive, so test
    # smaller pH trim bands first to prevent acid overshoot.
    for ec_trim in (0.05, 0.08, 0.10, 0.12):
        for ph_trim in (0.05, 0.06, 0.08, 0.10):
            for kp_ec in (0.8, 1.0, 1.2, 1.5):
                for kp_ph in (0.6, 0.8, 1.0, 1.2):
                    candidates.append(
                        Candidate(
                            kp_ec=kp_ec,
                            ki_ec=0.0,
                            kd_ec=0.0,
                            kp_ph=kp_ph,
                            ki_ph=args.base_ki_ph,
                            kd_ph=0.0,
                            ec_trim_band=ec_trim,
                            ph_trim_band=ph_trim,
                        )
                    )

    seen: set[tuple[float, ...]] = set()
    unique: list[Candidate] = []
    for candidate in candidates:
        key = tuple(round(v, 6) for v in asdict(candidate).values())
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique[: args.max_trials]


def _make_step_args(args: argparse.Namespace, candidate: Candidate) -> argparse.Namespace:
    return argparse.Namespace(
        ec_set=args.ec_set,
        ph_set=args.ph_set,
        change_at_s=args.change_at_s,
        ec_set_2=args.ec_set_2,
        ph_set_2=args.ph_set_2,
        ec_initial=args.ec_initial,
        ph_initial=args.ph_initial,
        stage=args.stage,
        duration_s=args.duration_s,
        plc_wait_s=args.plc_wait_s,
        sim_step_s=args.sim_step_s,
        pipe_tau_min=args.pipe_tau_min,
        pipe_t_min=args.pipe_t_min,
        q_w=args.q_w,
        log_every=args.log_every,
        disable_ec_loop=False,
        disable_ph_loop=False,
        kp_ec=candidate.kp_ec,
        ki_ec=candidate.ki_ec,
        kd_ec=candidate.kd_ec,
        kp_ph=candidate.kp_ph,
        ki_ph=candidate.ki_ph,
        kd_ph=candidate.kd_ph,
        ec_trim_band=candidate.ec_trim_band,
        ph_trim_band=candidate.ph_trim_band,
        ec_mae_max=TARGETS["ec_tail_mae"],
        ph_mae_max=TARGETS["ph_tail_mae"],
        ec_final_band=TARGETS["ec_final_abs"],
        ph_final_band=TARGETS["ph_final_abs"],
        ec_settle_band=TARGETS["ec_final_abs"],
        ph_settle_band=TARGETS["ph_final_abs"],
        ph_tail_drop_max=TARGETS["ph_tail_drop"],
        strict=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Tune PLC outlet EC/pH PID parameters until outlet acceptance targets pass.")
    parser.add_argument("--ec-set", type=float, default=1.5)
    parser.add_argument("--ph-set", type=float, default=5.9)
    parser.add_argument("--change-at-s", type=float, default=None)
    parser.add_argument("--ec-set-2", type=float, default=None)
    parser.add_argument("--ph-set-2", type=float, default=None)
    parser.add_argument("--ec-initial", type=float, default=0.0)
    parser.add_argument("--ph-initial", type=float, default=7.2)
    parser.add_argument("--stage", choices=["INI", "DEV", "MID", "LATE"], default="MID")
    parser.add_argument("--duration-s", type=float, default=1200.0)
    parser.add_argument("--plc-wait-s", type=float, default=1.0)
    parser.add_argument("--sim-step-s", type=float, default=None)
    parser.add_argument("--pipe-tau-min", type=float, default=None)
    parser.add_argument("--pipe-t-min", type=float, default=None)
    parser.add_argument("--q-w", type=float, default=None)
    parser.add_argument("--log-every", type=int, default=120)
    parser.add_argument("--max-trials", type=int, default=24)
    parser.add_argument("--base-kp-ec", type=float, default=1.2)
    parser.add_argument("--base-ki-ec", type=float, default=0.0)
    parser.add_argument("--base-kd-ec", type=float, default=0.0)
    parser.add_argument("--base-kp-ph", type=float, default=1.2)
    parser.add_argument("--base-ki-ph", type=float, default=0.01)
    parser.add_argument("--base-kd-ph", type=float, default=0.0)
    parser.add_argument("--base-ec-trim-band", type=float, default=0.10)
    parser.add_argument("--base-ph-trim-band", type=float, default=0.08)
    parser.add_argument("--preflight", action="store_true", help="Check PLC connection before tuning.")
    args = parser.parse_args()

    effective_step_s = float(args.sim_step_s if args.sim_step_s is not None else args.plc_wait_s)
    min_steps = 90
    total_steps = int(round(args.duration_s / effective_step_s))
    if total_steps < min_steps:
        old_duration = args.duration_s
        args.duration_s = effective_step_s * min_steps
        print(
            "Training duration extended so PLC can leave feedforward-only startup: "
            f"{old_duration:.1f}s -> {args.duration_s:.1f}s",
            flush=True,
        )

    if args.preflight:
        errors: list[str] = []
        _connect_plc(errors)
        if errors:
            raise SystemExit("; ".join(errors))

    out_dir = ROOT / "results" / "outlet_pid_tuning" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    history_csv = out_dir / "history.csv"
    history_json = out_dir / "history.json"
    best_json = out_dir / "best.json"

    fieldnames = [
        "trial",
        "passed",
        "score",
        "run_dir",
        *asdict(Candidate(0, 0, 0, 0, 0, 0, 0, 0)).keys(),
        "ec_tail_mae",
        "ph_tail_mae",
        "ec_final",
        "ph_final",
        "ec_final_abs",
        "ph_final_abs",
        "ph_tail_drop",
        "q_f_final",
        "q_a_final",
    ]

    history: list[dict[str, object]] = []
    best_row: dict[str, object] | None = None

    with history_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for trial, candidate in enumerate(_candidate_grid(args), start=1):
            print(f"\n=== Outlet tuning trial {trial}/{args.max_trials}: {candidate} ===", flush=True)
            try:
                run_dir, metrics = run_step_test(_make_step_args(args, candidate))
                passed = _passed(metrics, args.ec_set, args.ph_set)
                score = _score(metrics, args.ec_set, args.ph_set)
                row = {
                    "trial": trial,
                    "passed": passed,
                    "score": score,
                    "run_dir": str(run_dir),
                    **asdict(candidate),
                    **metrics,
                    "ec_final_abs": abs(float(metrics["ec_final"]) - args.ec_set),
                    "ph_final_abs": abs(float(metrics["ph_final"]) - args.ph_set),
                }
            except Exception as exc:
                row = {
                    "trial": trial,
                    "passed": False,
                    "score": 9999.0,
                    "run_dir": "",
                    **asdict(candidate),
                    "error": str(exc),
                }
                print(f"Trial failed: {exc}", flush=True)

            writer.writerow({name: row.get(name, "") for name in fieldnames})
            f.flush()
            history.append(row)
            history_json.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

            if best_row is None or float(row["score"]) < float(best_row["score"]):
                best_row = row
                best_json.write_text(json.dumps(best_row, ensure_ascii=False, indent=2), encoding="utf-8")

            if row.get("passed") is True:
                print("Outlet targets reached.", flush=True)
                print(f"Best params: {json.dumps(best_row, ensure_ascii=False, indent=2)}", flush=True)
                return 0

    print("Reached max trials before all outlet targets passed.", flush=True)
    if best_row:
        print(f"Best so far: {json.dumps(best_row, ensure_ascii=False, indent=2)}", flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
