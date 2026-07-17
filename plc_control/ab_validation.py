"""Acceptance criteria for PLC decoupler A/B reports."""

from __future__ import annotations

from pathlib import Path

import yaml


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
