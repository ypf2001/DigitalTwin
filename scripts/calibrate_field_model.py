"""田间数据驱动的分层土壤模型标定工具。

该工具把 CSV 田间数据转换成版本化 YAML 标定包。运行后只需激活标定包并
重新训练 SAC，不需要修改 Python、PLC 或 HMI 代码。

最小 CSV 列：
    dt_hours, irrigation_mm_h, ec_in_ds_m, ph_in, et_mm_h,
    theta_l1..theta_l4, ec_l1..ec_l4, ph_l1..ph_l4

也可只提供根区标量 theta、ec_soil、soil_ph。第一行作为初始状态，后续每行
表示上一时刻到本时刻的输入及本时刻测量值。若有 timestamp，可省略 dt_hours。
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_loader import load_config, reload_config
from soil_profile_v2 import LayeredSoilProfile


PARAMETERS = (
    ("k_sat_scale", 0.30, 3.00),
    ("drainage_beta_scale", 0.60, 1.60),
    ("field_capacity_drain_fraction", 0.10, 0.95),
    ("unsaturated_drain_fraction", 0.001, 0.080),
    ("irrigation_efficiency", 0.60, 1.00),
    ("et_scale", 0.60, 1.40),
    ("input_ec_scale", 0.60, 1.40),
    ("salt_transport_efficiency", 0.40, 1.00),
    ("ph_buffer_scale", 0.40, 2.50),
    ("ph_irrigation_response", 0.03, 0.80),
    ("ph_percolation_response", 0.02, 0.50),
)
PARAM_NAMES = tuple(x[0] for x in PARAMETERS)
LOW = np.asarray([x[1] for x in PARAMETERS], dtype=float)
HIGH = np.asarray([x[2] for x in PARAMETERS], dtype=float)

ALIASES = {
    "irrigation_mm_h": ("irrigation_mm_h", "irrigation", "I", "rain_irrigation_mm_h"),
    "ec_in_ds_m": ("ec_in_ds_m", "ec_in", "EC_in", "ec_drip"),
    "ph_in": ("ph_in", "pH_in", "ph_drip"),
    "et_mm_h": ("et_mm_h", "ET", "etc_mm_h"),
    "q_f_l_min": ("q_f_l_min", "q_f"),
    "stage": ("stage", "growth_stage"),
    "root_depth_mm": ("root_depth_mm", "root_depth"),
}


@dataclass
class FieldRow:
    dt_hours: float
    irrigation_mm_h: float
    ec_in_ds_m: float
    ph_in: float
    et_mm_h: float
    q_f_l_min: float
    stage: str
    root_depth_mm: float | None
    measurements: dict[str, float]


def _float(value: Any, default: float | None = None) -> float | None:
    if value is None or str(value).strip() == "":
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _first(row: dict[str, str], names: tuple[str, ...], default: Any = None) -> Any:
    for name in names:
        if name in row and str(row[name]).strip() != "":
            return row[name]
    return default


def _parse_timestamp(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_field_csv(path: Path, n_layers: int) -> list[FieldRow]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        raw = list(csv.DictReader(f))
    if len(raw) < 3:
        raise ValueError("田间 CSV 至少需要 3 行；建议覆盖多次灌溉/停灌动态并保留独立验证段")

    rows: list[FieldRow] = []
    previous_timestamp: datetime | None = None
    for index, source in enumerate(raw):
        timestamp = _parse_timestamp(source.get("timestamp", ""))
        dt = _float(source.get("dt_hours"))
        if dt is None and timestamp is not None and previous_timestamp is not None:
            dt = (timestamp - previous_timestamp).total_seconds() / 3600.0
        if index == 0 and dt is None:
            dt = 0.0
        if dt is None or dt < 0.0:
            raise ValueError(f"第 {index + 2} 行缺少有效 dt_hours，且无法从 timestamp 推导")
        previous_timestamp = timestamp or previous_timestamp

        measurements: dict[str, float] = {}
        for layer in range(1, n_layers + 1):
            for prefix in ("theta", "ec", "ph"):
                for key in (f"{prefix}_l{layer}", f"{prefix}_{layer}"):
                    value = _float(source.get(key))
                    if value is not None:
                        measurements[f"{prefix}_l{layer}"] = value
                        break
        for canonical, candidates in {
            "theta": ("theta", "theta_root"),
            "ec_soil": ("ec_soil", "ec_root"),
            "soil_ph": ("soil_ph", "ph_soil", "ph_root"),
        }.items():
            value = _float(_first(source, candidates))
            if value is not None:
                measurements[canonical] = value

        rows.append(FieldRow(
            dt_hours=float(dt),
            irrigation_mm_h=float(_float(_first(source, ALIASES["irrigation_mm_h"]), 0.0)),
            ec_in_ds_m=float(_float(_first(source, ALIASES["ec_in_ds_m"]), 0.0)),
            ph_in=float(_float(_first(source, ALIASES["ph_in"]), 7.0)),
            et_mm_h=float(_float(_first(source, ALIASES["et_mm_h"]), 0.0)),
            q_f_l_min=float(_float(_first(source, ALIASES["q_f_l_min"]), 0.0)),
            stage=str(_first(source, ALIASES["stage"], "bulking")).strip().lower(),
            root_depth_mm=_float(_first(source, ALIASES["root_depth_mm"])),
            measurements=measurements,
        ))

    measurement_count = sum(len(x.measurements) for x in rows)
    if measurement_count < max(10, n_layers * 3):
        raise ValueError("有效土壤观测过少；至少需要 10 个 theta/EC/pH 测量点")
    return rows


def _initial_vector(config: dict[str, Any]) -> np.ndarray:
    profile, ph = config["profile"], config["ph"]
    forcing = config.get("forcing", {})
    salinity = config.get("salinity", {})
    return np.asarray([
        1.0,
        1.0,
        profile.get("field_capacity_drain_fraction", 0.65),
        profile.get("unsaturated_drain_fraction", 0.015),
        forcing.get("irrigation_efficiency", 1.0),
        forcing.get("et_scale", 1.0),
        salinity.get("input_ec_scale", 1.0),
        salinity.get("transport_efficiency", 1.0),
        1.0,
        ph.get("irrigation_response_fraction", 0.18),
        ph.get("percolation_response_fraction", 0.12),
    ], dtype=float)


def _apply_initial_measurements(config: dict[str, Any], row: FieldRow, n_layers: int) -> None:
    profile = config["profile"]
    for prefix, key in (("theta", "theta_init"), ("ec", "ec_init_ds_m"), ("ph", "ph_init")):
        values = list(profile[key])
        found = False
        for layer in range(1, n_layers + 1):
            measured = row.measurements.get(f"{prefix}_l{layer}")
            if measured is not None:
                values[layer - 1] = measured
                found = True
        scalar_key = {"theta": "theta", "ec": "ec_soil", "ph": "soil_ph"}[prefix]
        if not found and scalar_key in row.measurements:
            values = [row.measurements[scalar_key]] * n_layers
        profile[key] = [float(x) for x in values]


def candidate_config(base: dict[str, Any], vector: np.ndarray, first_row: FieldRow) -> dict[str, Any]:
    cfg = copy.deepcopy(base)
    p, ph = cfg["profile"], cfg["ph"]
    values = dict(zip(PARAM_NAMES, np.asarray(vector, dtype=float)))
    p["k_sat_mm_h"] = [float(x) * values["k_sat_scale"] for x in base["profile"]["k_sat_mm_h"]]
    p["drainage_beta"] = [float(x) * values["drainage_beta_scale"] for x in base["profile"]["drainage_beta"]]
    p["field_capacity_drain_fraction"] = values["field_capacity_drain_fraction"]
    p["unsaturated_drain_fraction"] = values["unsaturated_drain_fraction"]
    cfg.setdefault("forcing", {})["irrigation_efficiency"] = values["irrigation_efficiency"]
    cfg["forcing"]["et_scale"] = values["et_scale"]
    cfg.setdefault("salinity", {})["input_ec_scale"] = values["input_ec_scale"]
    cfg["salinity"]["transport_efficiency"] = values["salt_transport_efficiency"]
    ph["buffer_water_equivalent_mm"] = [
        float(x) * values["ph_buffer_scale"] for x in base["ph"]["buffer_water_equivalent_mm"]
    ]
    ph["irrigation_response_fraction"] = values["ph_irrigation_response"]
    ph["percolation_response_fraction"] = values["ph_percolation_response"]
    _apply_initial_measurements(cfg, first_row, len(p["layer_thickness_mm"]))
    return cfg


def _prediction(soil: LayeredSoilProfile, key: str) -> float:
    if key == "theta":
        return soil.theta
    if key == "ec_soil":
        return soil.ec_soil
    if key == "soil_ph":
        return soil.ph_soil
    prefix, layer_text = key.split("_l")
    layer = int(layer_text) - 1
    return float({"theta": soil.theta_profile, "ec": soil.ec_profile, "ph": soil.ph_profile}[prefix][layer])


def evaluate(base: dict[str, Any], rows: list[FieldRow], vector: np.ndarray,
             end_index: int | None = None, start_score_index: int = 1) -> tuple[float, dict[str, Any]]:
    cfg = candidate_config(base, vector, rows[0])
    soil = LayeredSoilProfile(config=cfg, area_ha=float(cfg["profile"].get("area_ha", 1.0)))
    errors = {"theta": [], "ec": [], "ph": []}
    n = len(rows) if end_index is None else min(len(rows), end_index)

    for i, row in enumerate(rows[:n]):
        if row.root_depth_mm is not None:
            soil.set_growth_stage(row.stage, row.root_depth_mm)
        else:
            soil.set_growth_stage(row.stage)
        if i > 0:
            soil.step(
                I=row.irrigation_mm_h,
                EC_in=row.ec_in_ds_m,
                ET=row.et_mm_h,
                dt_hours=max(row.dt_hours, 1e-6),
                ph_in=row.ph_in,
                q_f_l_min=row.q_f_l_min,
                stage=row.stage,
            )
        if i < start_score_index:
            continue
        for key, measured in row.measurements.items():
            predicted = _prediction(soil, key)
            group = "theta" if key.startswith("theta") else "ec" if key.startswith("ec") else "ph"
            errors[group].append(predicted - measured)

    tolerances = {"theta": 0.020, "ec": 0.15, "ph": 0.20}
    metrics: dict[str, Any] = {}
    normalized_mse = []
    for group, values in errors.items():
        arr = np.asarray(values, dtype=float)
        if arr.size:
            metrics[f"{group}_mae"] = float(np.mean(np.abs(arr)))
            metrics[f"{group}_rmse"] = float(np.sqrt(np.mean(arr * arr)))
            metrics[f"{group}_count"] = int(arr.size)
            normalized_mse.extend((arr / tolerances[group]) ** 2)
        else:
            metrics[f"{group}_mae"] = None
            metrics[f"{group}_rmse"] = None
            metrics[f"{group}_count"] = 0
    score = float(np.sqrt(np.mean(normalized_mse))) if normalized_mse else float("inf")
    metrics["normalized_rmse"] = score
    return score, metrics


def optimize(base: dict[str, Any], rows: list[FieldRow], trials: int, seed: int,
             train_end: int) -> tuple[np.ndarray, list[tuple[float, np.ndarray]]]:
    rng = np.random.RandomState(seed)
    initial = np.clip(_initial_vector(base), LOW, HIGH)
    candidates: list[tuple[float, np.ndarray]] = []

    def record(vector: np.ndarray) -> None:
        score, _ = evaluate(base, rows, vector, end_index=train_end)
        candidates.append((score, vector.copy()))

    record(initial)
    # 全局均匀搜索，避免只在文献占位参数附近收敛。
    for _ in range(max(1, trials)):
        record(rng.uniform(LOW, HIGH))

    # 围绕当前最优解逐级缩小搜索半径。
    best = min(candidates, key=lambda item: item[0])[1]
    span = HIGH - LOW
    for radius in (0.20, 0.08, 0.03):
        for _ in range(max(12, trials // 5)):
            record(np.clip(best + rng.normal(0.0, radius, size=best.size) * span, LOW, HIGH))
        best = min(candidates, key=lambda item: item[0])[1]
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1], candidates


def _relative_ranges(best: np.ndarray, ranked: list[tuple[float, np.ndarray]]) -> dict[str, float]:
    top = np.asarray([x[1] for x in ranked[:max(8, min(30, len(ranked) // 10))]])
    cv = np.std(top, axis=0) / np.maximum(np.abs(best), 1e-6)
    mapping = {
        "profile.k_sat_mm_h": cv[0],
        "profile.drainage_beta": cv[1],
        "profile.field_capacity_drain_fraction": cv[2],
        "profile.unsaturated_drain_fraction": cv[3],
        "forcing.irrigation_efficiency": cv[4],
        "forcing.et_scale": cv[5],
        "salinity.input_ec_scale": cv[6],
        "salinity.transport_efficiency": cv[7],
        "ph.buffer_water_equivalent_mm": cv[8],
        "ph.irrigation_response_fraction": cv[9],
        "ph.percolation_response_fraction": cv[10],
    }
    return {key: float(np.clip(value * 2.0, 0.03, 0.35)) for key, value in mapping.items()}


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_plain(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="用田间 CSV 标定分层土壤数字孪生")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--trials", type=int, default=300)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--validation-fraction", type=float, default=0.20)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--activate", action="store_true", help="复制为 config/calibration/active.yaml")
    args = parser.parse_args()

    csv_path = args.csv_path.resolve()
    if not csv_path.is_file():
        raise FileNotFoundError(csv_path)
    base = copy.deepcopy(load_config().soil_v2())
    if not base:
        raise RuntimeError("缺少 soil_v2 配置")
    n_layers = len(base["profile"]["layer_thickness_mm"])
    rows = load_field_csv(csv_path, n_layers)
    train_end = max(2, min(len(rows) - 1, int(round(len(rows) * (1.0 - args.validation_fraction)))))

    best, ranked = optimize(base, rows, max(10, args.trials), args.seed, train_end)
    train_score, train_metrics = evaluate(base, rows, best, end_index=train_end)
    _, full_metrics = evaluate(base, rows, best)
    validation_score, validation_metrics = evaluate(
        base, rows, best, end_index=len(rows), start_score_index=train_end
    )
    fitted = candidate_config(base, best, rows[0])

    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    now = datetime.now(timezone.utc)
    version = f"field-{now.strftime('%Y%m%d-%H%M%S')}-{digest[:8]}"
    fitted["parameter_status"] = "field_calibrated"
    fitted["parameter_version"] = version
    fitted["default_model"] = "layered_v2"
    fitted["domain_randomization"] = {"relative_range": _relative_ranges(best, ranked)}

    profile = {
        "calibration": {
            "id": version,
            "created_at": now.isoformat(),
            "source_csv": str(csv_path),
            "source_sha256": digest,
            "row_count": len(rows),
            "train_rows": train_end,
            "validation_rows": len(rows) - train_end,
            "optimizer_trials": len(ranked),
            "train_score": train_score,
            "validation_score": validation_score,
            "train_metrics": train_metrics,
            "validation_metrics": validation_metrics,
            "full_metrics": full_metrics,
            "fitted_parameters": dict(zip(PARAM_NAMES, best.tolist())),
        },
        "soil_v2": fitted,
    }

    output = args.output or (ROOT / "config" / "calibration" / f"{version}.yaml")
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(_plain(profile), allow_unicode=True, sort_keys=False), encoding="utf-8")

    report_path = output.with_suffix(".report.json")
    report_path.write_text(json.dumps(_plain(profile["calibration"]), ensure_ascii=False, indent=2), encoding="utf-8")
    if args.activate:
        active = ROOT / "config" / "calibration" / "active.yaml"
        active.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output, active)
        reload_config()
        print(f"已激活: {active}")

    print(json.dumps({
        "profile": str(output),
        "report": str(report_path),
        "version": version,
        "train_metrics": train_metrics,
        "validation_metrics": validation_metrics,
        "next": "python train_sac.py --stage MID --fresh --soil-model layered_v2",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
