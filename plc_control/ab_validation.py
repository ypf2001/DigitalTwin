"""Acceptance criteria for PLC decoupler A/B reports."""

from __future__ import annotations

import math
from pathlib import Path

import yaml


def _as_float(row: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _as_bool(row: dict, key: str, default: bool = False) -> bool:
    value = row.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def summarize_ab_rows(rows: list[dict], baseline_window_s: float = 120.0) -> dict:
    """Build A/B metrics using the pre-step process value as the coupling baseline."""
    if baseline_window_s <= 0.0:
        raise ValueError("baseline_window_s must be positive")

    results = []
    weights = sorted({_as_float(row, "weight") for row in rows})
    for weight in weights:
        for disturbance in ("ec", "ph"):
            selected = sorted(
                (
                    row for row in rows
                    if abs(_as_float(row, "weight") - weight) < 1e-9
                    and str(row.get("disturbance")) == disturbance
                ),
                key=lambda row: _as_float(row, "time_s"),
            )
            if not selected:
                continue

            stepped_setpoint = "ec_set" if disturbance == "ec" else "ph_set"
            initial_setpoint = _as_float(selected[0], stepped_setpoint)
            step_row = next(
                (
                    row for row in selected
                    if abs(_as_float(row, stepped_setpoint) - initial_setpoint) > 1e-9
                ),
                None,
            )
            if step_row is None:
                raise ValueError(
                    f"no {disturbance} setpoint step found for weight={weight}"
                )
            step_time_s = _as_float(step_row, "time_s")
            pre_step = [row for row in selected if _as_float(row, "time_s") < step_time_s]
            post_step = [row for row in selected if _as_float(row, "time_s") >= step_time_s]
            baseline_rows = [
                row for row in pre_step
                if _as_float(row, "time_s") >= step_time_s - baseline_window_s
            ]
            if not baseline_rows or not post_step:
                raise ValueError(
                    f"insufficient pre/post-step samples for weight={weight}, disturbance={disturbance}"
                )

            cross = "ph_actual" if disturbance == "ec" else "ec_actual"
            cross_baseline = sum(_as_float(row, cross) for row in baseline_rows) / len(baseline_rows)
            q_f_post = [_as_float(row, "q_f_cmd") for row in post_step]
            q_a_post = [_as_float(row, "q_a_cmd") for row in post_step]
            results.append({
                "weight": weight,
                "disturbance": disturbance,
                "ec_mae": sum(abs(_as_float(row, "ec_actual") - _as_float(row, "ec_set")) for row in post_step) / len(post_step),
                "ph_mae": sum(abs(_as_float(row, "ph_actual") - _as_float(row, "ph_set")) for row in post_step) / len(post_step),
                "cross_coupling_peak": max(abs(_as_float(row, cross) - cross_baseline) for row in post_step),
                "cross_coupling_metric": "pre_step_baseline_delta_peak",
                "cross_baseline": cross_baseline,
                "step_time_s": step_time_s,
                "baseline_window_s": baseline_window_s,
                "baseline_samples": len(baseline_rows),
                "q_f_saturation_count": sum(_as_bool(row, "q_f_saturated") or _as_bool(row, "q_f_limited") for row in selected),
                "q_a_saturation_count": sum(_as_bool(row, "q_a_saturated") or _as_bool(row, "q_a_limited") for row in selected),
                "q_f_rms": math.sqrt(sum(value * value for value in q_f_post) / len(q_f_post)),
                "q_a_rms": math.sqrt(sum(value * value for value in q_a_post) / len(q_a_post)),
                "alarm_count": sum(_as_bool(row, "alarm") for row in selected),
                "communication_failures": sum(not _as_bool(row, "remote_comms_ok") for row in selected),
                "setpoint_protection_count": sum(_as_bool(row, "setpoint_protection") for row in selected),
                "output_direction_ok": all(
                    math.isfinite(_as_float(row, "q_f_cmd"))
                    and math.isfinite(_as_float(row, "q_a_cmd"))
                    for row in selected
                ),
                "decoupler_valid_all": all(_as_bool(row, "decoupler_valid") for row in selected),
            })

    by_weight = {}
    for result in results:
        by_weight.setdefault(str(result["weight"]), []).append(result)
    return {
        "weights": results,
        "by_weight": by_weight,
        "cross_coupling_metric": "pre_step_baseline_delta_peak",
        "decoupler_enabled_during_test": any(_as_bool(row, "decoupler_enable") for row in rows),
    }


def load_ab_criteria(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    criteria = data.get("ab_validation", data)
    if not isinstance(criteria, dict):
        raise ValueError("ab_validation must be a mapping")
    return criteria


def evaluate_ab_summary(summary: dict, criteria: dict) -> dict:
    """Compare every candidate against the same baseline in both directions."""
    rows = summary.get("weights", [])
    baseline_weight = float(criteria.get("baseline_weight", 0.0))
    baseline = {
        str(row["disturbance"]): row
        for row in rows
        if abs(float(row["weight"]) - baseline_weight) < 1e-9
    }
    disturbances = sorted(baseline)
    candidates = [
        float(weight) for weight in criteria.get("candidate_weights", [])
    ]
    reduction = float(criteria.get("min_cross_coupling_reduction_fraction", 0.0))
    result_rows = []
    for weight in candidates:
        candidate = {
            str(row["disturbance"]): row
            for row in rows
            if abs(float(row["weight"]) - weight) < 1e-9
        }
        checks = {
            "all_disturbances_present": all(name in candidate for name in disturbances),
            "cross_coupling_improved": True,
            "ec_error_not_degraded": True,
            "ph_error_not_degraded": True,
            "q_f_saturation_not_increased": True,
            "q_a_saturation_not_increased": True,
            "alarms_not_increased": True,
            "communication_failures_not_increased": True,
            "setpoint_protection_not_active": True,
        }
        details = {}
        for name in disturbances:
            if name not in candidate:
                continue
            base = baseline[name]
            test = candidate[name]
            details[name] = {
                "cross_reduction_fraction": (
                    1.0 - float(test["cross_coupling_peak"])
                    / max(float(base["cross_coupling_peak"]), 1e-9)
                ),
                "ec_mae_delta": float(test["ec_mae"]) - float(base["ec_mae"]),
                "ph_mae_delta": float(test["ph_mae"]) - float(base["ph_mae"]),
            }
            checks["cross_coupling_improved"] &= (
                float(test["cross_coupling_peak"])
                <= float(base["cross_coupling_peak"]) * (1.0 - reduction)
            )
            checks["ec_error_not_degraded"] &= (
                float(test["ec_mae"]) - float(base["ec_mae"])
                <= float(criteria.get("max_ec_mae_degradation_abs", 0.0))
            )
            checks["ph_error_not_degraded"] &= (
                float(test["ph_mae"]) - float(base["ph_mae"])
                <= float(criteria.get("max_ph_mae_degradation_abs", 0.0))
            )
            checks["q_f_saturation_not_increased"] &= (
                int(test["q_f_saturation_count"]) - int(base["q_f_saturation_count"])
                <= int(criteria.get("max_q_f_saturation_increase", 0))
            )
            checks["q_a_saturation_not_increased"] &= (
                int(test["q_a_saturation_count"]) - int(base["q_a_saturation_count"])
                <= int(criteria.get("max_q_a_saturation_increase", 0))
            )
            checks["alarms_not_increased"] &= (
                int(test["alarm_count"]) - int(base["alarm_count"])
                <= int(criteria.get("max_alarm_increase", 0))
            )
            checks["communication_failures_not_increased"] &= (
                int(test["communication_failures"])
                - int(base["communication_failures"])
                <= int(criteria.get("max_communication_failure_increase", 0))
            )
            checks["setpoint_protection_not_active"] &= (
                int(test.get("setpoint_protection_count", 0))
                <= int(criteria.get("max_setpoint_protection_count", 0))
            )
        passed = bool(all(checks.values()))
        result_rows.append({"weight": weight, "passed": passed, "checks": checks, "details": details})

    return {
        "baseline_weight": baseline_weight,
        "criteria": criteria,
        "candidates": result_rows,
        "passed": bool(any(row["passed"] for row in result_rows)),
        "enable_decoupler": False,
    }
