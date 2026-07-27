"""Metrics and gates for acid-to-EC constrained-decoupling E4 trials."""

from __future__ import annotations

import math
from statistics import mean, median


def _f(row: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _b(row: dict, key: str, default: bool = False) -> bool:
    value = row.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _recovery_time(rows: list[dict], start_s: float, low: float, high: float) -> float:
    post = [row for row in rows if _f(row, "time_s") >= start_s]
    for index in range(max(0, len(post) - 2)):
        window = post[index:index + 3]
        if len(window) == 3 and all(low <= _f(row, "ph_actual") <= high for row in window):
            return max(0.0, _f(window[0], "time_s") - start_s)
    return math.inf


def summarize_constrained_rows(rows: list[dict], *, disturbance_time_s: float,
                               baseline_window_s: float, delay_s: float,
                               ph_low: float = 5.8, ph_high: float = 6.5) -> list[dict]:
    """Return one metric row per point/weight/disturbance/repetition."""
    groups = {}
    for row in rows:
        key = (str(row["point"]), _f(row, "weight"), str(row["disturbance"]), int(row["repetition"]))
        groups.setdefault(key, []).append(row)
    results = []
    for (point, weight, disturbance, repetition), selected in sorted(groups.items()):
        selected.sort(key=lambda row: _f(row, "time_s"))
        baseline = [
            row for row in selected
            if disturbance_time_s - baseline_window_s <= _f(row, "time_s") < disturbance_time_s
        ]
        post = [row for row in selected if _f(row, "time_s") >= disturbance_time_s]
        if not baseline or not post:
            raise ValueError(f"insufficient E4 baseline/post data for {(point, weight, disturbance, repetition)}")
        dt_values = [
            _f(post[index], "time_s") - _f(post[index - 1], "time_s")
            for index in range(1, len(post))
        ]
        dt_s = median(dt_values) if dt_values else 0.0
        baseline_ec = mean(_f(row, "ec_actual") for row in baseline)
        delayed = [row for row in post if _f(row, "time_s") >= disturbance_time_s + delay_s]
        evaluation = delayed or post
        tail_count = max(1, int(math.ceil(0.20 * len(evaluation))))
        recovery_s = _recovery_time(selected, disturbance_time_s, ph_low, ph_high)
        after_recovery = [
            row for row in post
            if math.isfinite(recovery_s) and _f(row, "time_s") >= disturbance_time_s + recovery_s
        ]
        results.append({
            "point": point, "weight": weight, "disturbance": disturbance,
            "repetition": repetition, "baseline_ec": baseline_ec,
            "ec_cross_peak": max(abs(_f(row, "ec_actual") - baseline_ec) for row in post),
            "ec_mae": mean(abs(_f(row, "ec_actual") - _f(row, "ec_set")) for row in evaluation),
            "ec_tail_mae": mean(abs(_f(row, "ec_actual") - _f(row, "ec_set")) for row in evaluation[-tail_count:]),
            "ec_iae": sum(abs(_f(row, "ec_actual") - _f(row, "ec_set")) * dt_s for row in evaluation),
            "ph_recovery_s": recovery_s,
            "ph_min": min(_f(row, "ph_actual") for row in post),
            "ph_max": max(_f(row, "ph_actual") for row in post),
            "ph_band_occupancy_after_recovery": (
                mean(ph_low <= _f(row, "ph_actual") <= ph_high for row in after_recovery)
                if after_recovery else 0.0
            ),
            "flush_requested": any(_b(row, "ph_flush_request") for row in post),
            "acid_while_low": any(
                _f(row, "ph_actual") < ph_low and _f(row, "q_a_cmd") > 1e-6 for row in post
            ),
            "batch_reject_count": sum(_b(row, "batch_reject") for row in post),
            "saturation_count": sum(
                _b(row, "q_f_limited") or _b(row, "q_a_limited") for row in post
            ),
            "alarm_count": sum(_b(row, "alarm") for row in post),
            "communication_failure_count": sum(not _b(row, "remote_comms_ok") for row in post),
            "decoupling_limited_count": sum(_b(row, "decoupling_limited") for row in post),
        })
    return results


def evaluate_constrained_ab(metrics: list[dict], criteria: dict,
                            *, point: str = "medium") -> dict:
    """Select the lowest medium-point weight satisfying every paired gate."""
    baseline_weight = float(criteria.get("baseline_weight", 0.0))
    candidates = [float(value) for value in criteria.get("candidate_weights", (0.1, 0.25))]

    def rows(weight: float, disturbance: str) -> list[dict]:
        return sorted(
            [row for row in metrics if row["point"] == point and abs(float(row["weight"]) - weight) < 1e-9
             and row["disturbance"] == disturbance],
            key=lambda row: int(row["repetition"]),
        )

    verdicts = []
    for weight in candidates:
        base_high, test_high = rows(baseline_weight, "ph_high"), rows(weight, "ph_high")
        base_ec, test_ec = rows(baseline_weight, "ec_step"), rows(weight, "ec_step")
        base_low, test_low = rows(baseline_weight, "ph_low"), rows(weight, "ph_low")
        complete = all(len(group) == int(criteria.get("repetitions", 3)) for group in (
            base_high, test_high, base_ec, test_ec, base_low, test_low
        ))
        reductions = [
            1.0 - float(test["ec_cross_peak"]) / max(float(base["ec_cross_peak"]), 1e-9)
            for base, test in zip(base_high, test_high)
        ] if complete else []
        iae_ratio = (
            mean(float(row["ec_iae"]) for row in test_ec)
            / max(mean(float(row["ec_iae"]) for row in base_ec), 1e-9)
        ) if complete else math.inf
        recovery_ratio = (
            mean(float(row["ph_recovery_s"]) for row in test_high)
            / max(mean(float(row["ph_recovery_s"]) for row in base_high), 1e-9)
        ) if complete else math.inf
        checks = {
            "complete_repetitions": complete,
            "mean_cross_reduction": bool(reductions) and mean(reductions) >= float(criteria["min_cross_coupling_reduction_fraction"]),
            "no_repeat_cross_degradation": bool(reductions) and min(reductions) >= 0.0,
            "ec_iae_not_degraded": iae_ratio <= 1.0 + float(criteria["max_main_loop_iae_degradation_fraction"]),
            "ph_recovery_not_degraded": recovery_ratio <= 1.0 + float(criteria["max_ph_recovery_degradation_fraction"]),
            "no_ph_undershoot": complete and min(float(row["ph_min"]) for row in test_high) >= float(criteria["ph_band_low"]),
            "ec_accuracy": complete and max(float(row["ec_mae"]) for row in test_ec) <= float(criteria["ec_mae_max"]),
            "ec_tail_accuracy": complete and max(float(row["ec_tail_mae"]) for row in test_ec) <= float(criteria["ec_tail_mae_max"]),
            "ph_band_occupancy": complete and min(float(row["ph_band_occupancy_after_recovery"]) for row in test_high + test_ec) >= float(criteria["ph_band_occupancy_min"]),
            "low_ph_stops_acid": complete and all(row["flush_requested"] and not row["acid_while_low"] for row in test_low),
            "no_saturation_increase": complete and sum(row["saturation_count"] for row in test_high + test_ec + test_low) <= sum(row["saturation_count"] for row in base_high + base_ec + base_low),
            "no_safety_event_increase": complete and sum(row["batch_reject_count"] + row["alarm_count"] + row["communication_failure_count"] for row in test_high + test_ec + test_low) <= sum(row["batch_reject_count"] + row["alarm_count"] + row["communication_failure_count"] for row in base_high + base_ec + base_low),
        }
        verdicts.append({
            "weight": weight, "passed": all(checks.values()), "checks": checks,
            "mean_cross_reduction": mean(reductions) if reductions else -math.inf,
            "minimum_cross_reduction": min(reductions) if reductions else -math.inf,
            "ec_iae_ratio": iae_ratio, "ph_recovery_ratio": recovery_ratio,
        })
    passing = sorted(row["weight"] for row in verdicts if row["passed"])
    return {"point": point, "candidates": verdicts, "passed": bool(passing),
            "selected_weight": passing[0] if passing else None}

