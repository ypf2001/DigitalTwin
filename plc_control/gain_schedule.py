"""Work-point scheduling and local 2x2 gain identification helpers.

The PLC receives only one validated local matrix at a time.  The complete
nonlinear schedule stays on the supervisory computer and is selected from the
current operating point.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import yaml


GAIN_KEYS = ("g_ec_f", "g_ec_a", "g_ph_f", "g_ph_a")
OUTPUT_KEYS = {"ec": "ec", "ph": "ph"}


def load_gain_schedule(path: str | Path) -> dict:
    """Load and minimally validate a gain schedule YAML file."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"gain schedule must be a mapping: {path}")
    if "gain_schedule" in data:
        data = data["gain_schedule"] or {}
        if not isinstance(data, dict):
            raise ValueError(f"gain_schedule must be a mapping: {path}")
    data.setdefault("enabled", False)
    data.setdefault("selection", {})
    data.setdefault("stages", {})
    return data


def _point_matrix(point: dict) -> np.ndarray:
    gains = point.get("gains", point)
    try:
        return np.array(
            [
                [float(gains["g_ec_f"]), float(gains["g_ec_a"])],
                [float(gains["g_ph_f"]), float(gains["g_ph_a"])],
            ],
            dtype=float,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("gain point is missing the four gain values") from exc


def gain_diagnostics(point: dict, determinant_min: float = 1e-6) -> dict:
    """Return determinant, condition number, signs, and deployability."""
    matrix = _point_matrix(point)
    determinant = float(np.linalg.det(matrix))
    try:
        condition_number = float(np.linalg.cond(matrix))
    except np.linalg.LinAlgError:
        condition_number = math.inf
    finite = bool(np.isfinite(matrix).all())
    signs_ok = bool(matrix[0, 0] > 0.0 and matrix[1, 1] < 0.0)
    valid = bool(
        finite
        and abs(determinant) >= float(determinant_min)
        and np.isfinite(condition_number)
        and signs_ok
    )
    return {
        "determinant": determinant,
        "condition_number": condition_number,
        "signs_ok": signs_ok,
        "valid": valid,
    }


def _step_rows(rows: list[dict], step_name: str) -> list[dict]:
    return [row for row in rows if str(row.get("step_name", "")) == step_name]


def _numeric(row: dict, key: str) -> float:
    value = row.get(key)
    if value is None or value == "":
        raise ValueError(f"missing numeric column {key}")
    return float(value)


def estimate_step(rows: list[dict], input_key: str, output_key: str,
                  step_name: str, edge_fraction: float = 0.15,
                  input_start_override: float | None = None) -> dict:
    """Estimate one local step gain, delay, and first-order time constant.

    The beginning and end medians make the estimate tolerant of sensor noise.
    The input step itself is read from the recorded command, so saturation or
    a failed manual-mode transition is visible as a zero/invalid step.
    """
    phase = _step_rows(rows, step_name)
    if len(phase) < 4:
        raise ValueError(f"step {step_name!r} has too few samples")
    # Keep the edge window short enough that a delayed transition does not
    # contaminate the baseline estimate.  For a four-sample smoke test this
    # still yields one sample; long live tests use the median of several.
    n_edge = max(1, min(len(phase) // 3, int(len(phase) * edge_fraction)))
    u_start = (
        float(input_start_override)
        if input_start_override is not None
        else float(np.median([_numeric(row, input_key) for row in phase[:n_edge]]))
    )
    u_end = float(np.median([_numeric(row, input_key) for row in phase[-n_edge:]]))
    y_start = float(np.median([_numeric(row, output_key) for row in phase[:n_edge]]))
    y_end = float(np.median([_numeric(row, output_key) for row in phase[-n_edge:]]))
    delta_u = u_end - u_start
    delta_y = y_end - y_start
    if abs(delta_u) < 1e-9:
        raise ValueError(f"step {step_name!r} has no effective {input_key} change")
    gain = delta_y / delta_u

    t0 = _numeric(phase[0], "timestamp_s")
    threshold = y_start + 0.1 * delta_y
    response_time = None
    tau_s = None
    for row in phase[n_edge:]:
        y = _numeric(row, output_key)
        if (delta_y >= 0.0 and y >= threshold) or (delta_y < 0.0 and y <= threshold):
            response_time = max(0.0, _numeric(row, "timestamp_s") - t0)
            break
    tau_level = y_start + 0.632 * delta_y
    for row in phase[n_edge:]:
        y = _numeric(row, output_key)
        if (delta_y >= 0.0 and y >= tau_level) or (delta_y < 0.0 and y <= tau_level):
            tau_s = max(0.0, _numeric(row, "timestamp_s") - t0 - (response_time or 0.0))
            break
    residual = float(np.std([_numeric(row, output_key) for row in phase[-n_edge:]]))
    signal_to_noise = abs(delta_y) / max(residual, 1e-9)
    return {
        "step_name": step_name,
        "input": input_key,
        "output": output_key,
        "delta_input": delta_u,
        "delta_output": delta_y,
        "gain": gain,
        "delay_s": response_time,
        "tau_s": tau_s,
        "residual_std": residual,
        "signal_to_noise": signal_to_noise,
    }


def identify_local_gain(rows: Iterable[dict], stage: str, operating_point: str,
                        determinant_min: float = 1e-6) -> dict:
    """Identify one operating point from four labelled step phases."""
    selected = [
        row for row in rows
        if str(row.get("stage", "")).upper() == stage.upper()
        and str(row.get("operating_point", "")) == operating_point
    ]
    if not selected:
        raise ValueError(f"no rows for {stage}/{operating_point}")

    steps = {
        "f_pos": "fertilizer_pos",
        "f_neg": "fertilizer_neg",
        "a_pos": "acid_pos",
        "a_neg": "acid_neg",
    }
    def prior_input(step_name: str, input_key: str) -> float | None:
        first = next((index for index, row in enumerate(selected)
                      if str(row.get("step_name", "")) == step_name), None)
        if first is None or first == 0:
            return None
        return _numeric(selected[first - 1], input_key)

    responses = {
        "ec_f_pos": estimate_step(selected, "q_f_cmd", "ec", steps["f_pos"], input_start_override=prior_input(steps["f_pos"], "q_f_cmd")),
        "ec_f_neg": estimate_step(selected, "q_f_cmd", "ec", steps["f_neg"], input_start_override=prior_input(steps["f_neg"], "q_f_cmd")),
        "ec_a_pos": estimate_step(selected, "q_a_cmd", "ec", steps["a_pos"], input_start_override=prior_input(steps["a_pos"], "q_a_cmd")),
        "ec_a_neg": estimate_step(selected, "q_a_cmd", "ec", steps["a_neg"], input_start_override=prior_input(steps["a_neg"], "q_a_cmd")),
        "ph_f_pos": estimate_step(selected, "q_f_cmd", "ph", steps["f_pos"], input_start_override=prior_input(steps["f_pos"], "q_f_cmd")),
        "ph_f_neg": estimate_step(selected, "q_f_cmd", "ph", steps["f_neg"], input_start_override=prior_input(steps["f_neg"], "q_f_cmd")),
        "ph_a_pos": estimate_step(selected, "q_a_cmd", "ph", steps["a_pos"], input_start_override=prior_input(steps["a_pos"], "q_a_cmd")),
        "ph_a_neg": estimate_step(selected, "q_a_cmd", "ph", steps["a_neg"], input_start_override=prior_input(steps["a_neg"], "q_a_cmd")),
    }

    def central(pos: str, neg: str) -> float:
        return float((responses[pos]["gain"] + responses[neg]["gain"]) / 2.0)

    gains = {
        "g_ec_f": central("ec_f_pos", "ec_f_neg"),
        "g_ec_a": central("ec_a_pos", "ec_a_neg"),
        "g_ph_f": central("ph_f_pos", "ph_f_neg"),
        "g_ph_a": central("ph_a_pos", "ph_a_neg"),
    }
    point = {
        "id": operating_point,
        "stage": stage.upper(),
        "ec": float(selected[0].get("ec_set", selected[0].get("ec", 0.0))),
        "ph": float(selected[0].get("ph_set", selected[0].get("ph", 7.0))),
        "q_f": float(selected[0].get("q_f_baseline", selected[0].get("q_f_cmd", 0.0))),
        "q_a": float(selected[0].get("q_a_baseline", selected[0].get("q_a_cmd", 0.0))),
        "gains": gains,
        "delay_s": float(np.nanmedian([
            responses[key]["delay_s"] for key in responses
            if responses[key]["delay_s"] is not None
        ] or [0.0])),
        "tau_s": float(np.nanmedian([
            responses[key]["tau_s"] for key in responses
            if responses[key]["tau_s"] is not None
        ] or [0.0])),
        "responses": responses,
    }
    point.update(gain_diagnostics(point, determinant_min=determinant_min))
    snr = [response["signal_to_noise"] for response in responses.values()]
    point["confidence"] = float(min(1.0, max(0.0, np.median(snr) / 10.0)))
    point["valid"] = bool(point["valid"] and point["confidence"] >= 0.5)
    return point


def select_gain_point(schedule: dict, stage: str, ec: float, ph: float,
                      q_f: float, q_a: float) -> dict | None:
    """Select the nearest valid point using configured operating scales."""
    stage_data = schedule.get("stages", {}).get(str(stage).upper(), {})
    points = stage_data.get("points", []) if isinstance(stage_data, dict) else []
    if not schedule.get("enabled", False) or not points:
        return None
    scales = schedule.get("selection", {})
    scale_ec = max(float(scales.get("ec_scale", 1.0)), 1e-9)
    scale_ph = max(float(scales.get("ph_scale", 1.0)), 1e-9)
    scale_qf = max(float(scales.get("q_f_scale", 1.0)), 1e-9)
    scale_qa = max(float(scales.get("q_a_scale", 1.0)), 1e-9)
    candidates = []
    for point in points:
        diagnostics = gain_diagnostics(point, determinant_min=float(scales.get("determinant_min", 1e-6)))
        if not point.get("valid", diagnostics["valid"]) or not diagnostics["valid"]:
            continue
        distance = sum((a - b) ** 2 for a, b in (
            (float(point.get("ec", 0.0)) / scale_ec, float(ec) / scale_ec),
            (float(point.get("ph", 7.0)) / scale_ph, float(ph) / scale_ph),
            (float(point.get("q_f", 0.0)) / scale_qf, float(q_f) / scale_qf),
            (float(point.get("q_a", 0.0)) / scale_qa, float(q_a) / scale_qa),
        ))
        candidates.append((distance, point))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def read_csv_rows(path: str | Path) -> list[dict]:
    with Path(path).open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_json(path: str | Path, value: dict) -> None:
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
