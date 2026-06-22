"""数字孪生 SAC 实验一键流水线。

执行顺序：
1. 母液混合可控域实验；
2. 短期单次灌溉事件响应；
3. 从头训练 SAC（默认 INI/DEV/MID/LATE 四阶段；--single-stage 时只训练指定阶段）；
4. 固定策略与 SAC 水肥控制策略离线对比；
5. SAC 完整生育期评估；
6. 固定策略短期仿真与 T1/T2 灌溉制度季节对比。

前两步是安全门。若固定策略不在安全区域，或短期事件触发烧苗，
流水线会立即停止，避免使用错误配置训练 SAC。
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = ROOT / "results"
logger = logging.getLogger(__name__)

PLC_PH_TARGETS = {
    "INI": 6.2,
    "DEV": 6.1,
    "MID": 5.9,
    "LATE": 6.1,
}


def _latest_run_dir(experiment_name: str) -> Path:
    """返回指定实验最近生成的时间戳目录。"""
    base = RESULTS_ROOT / experiment_name
    runs = sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.name)
    if not runs:
        raise RuntimeError(f"实验没有生成结果目录: {base}")
    return runs[-1]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _float_or_default(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _mean_abs_error(rows: list[dict[str, str]], actual_key: str, target_key: str, default_target: float = 0.0) -> float:
    if not rows:
        return 0.0
    errors = [
        abs(_float_or_default(row.get(actual_key)) - _float_or_default(row.get(target_key), default_target))
        for row in rows
    ]
    return sum(errors) / len(errors)


def _error_metrics(rows: list[dict[str, str]], actual_key: str, target_key: str) -> tuple[float, float, float]:
    if not rows:
        return 0.0, 0.0, 0.0
    errors = [
        _float_or_default(row.get(actual_key)) - _float_or_default(row.get(target_key))
        for row in rows
    ]
    abs_errors = [abs(error) for error in errors]
    mae = sum(abs_errors) / len(abs_errors)
    rmse = (sum(error * error for error in errors) / len(errors)) ** 0.5
    max_error = max(abs_errors)
    return mae, rmse, max_error


def _ph_target(row: dict[str, str]) -> float:
    if "target_ph" in row:
        return _float_or_default(row.get("target_ph"), 6.0)
    stage = str(row.get("stage", "")).upper()
    return PLC_PH_TARGETS.get(stage, _float_or_default(row.get("ph_set"), 6.0))


def _compute_plc_npk_metrics_from_csv(run_dir: Path) -> dict[str, float]:
    csv_path = run_dir / "full_season_plc_timeseries.csv"
    if not csv_path.exists():
        return {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return {}

    ec_errors = [
        abs(_float_or_default(row.get("ec_soil")) - _float_or_default(row.get("target_ec")))
        for row in rows
    ]
    ph_errors = [
        abs(_float_or_default(row.get("soil_ph_est"), 7.0) - _ph_target(row))
        for row in rows
    ]
    n_mae, n_rmse, n_max = _error_metrics(rows, "n_actual", "n_target")
    p_mae, p_rmse, p_max = _error_metrics(rows, "p_actual", "p_target")
    k_mae, k_rmse, k_max = _error_metrics(rows, "k_actual", "k_target")
    return {
        "EC_MAE": sum(ec_errors) / len(ec_errors),
        "pH_MAE": sum(ph_errors) / len(ph_errors),
        "N_MAE": n_mae,
        "P_MAE": p_mae,
        "K_MAE": k_mae,
        "N_RMSE": n_rmse,
        "P_RMSE": p_rmse,
        "K_RMSE": k_rmse,
        "N_Max_Error": n_max,
        "P_Max_Error": p_max,
        "K_Max_Error": k_max,
    }


def _extract_plc_npk_metrics(summary: dict[str, Any], run_dir: Path) -> tuple[dict[str, float], str]:
    metric_keys = ["EC_MAE", "pH_MAE", "N_MAE", "P_MAE", "K_MAE"]
    optional_metric_keys = [
        "N_RMSE",
        "P_RMSE",
        "K_RMSE",
        "N_Max_Error",
        "P_Max_Error",
        "K_Max_Error",
    ]
    sources: list[tuple[str, dict[str, Any]]] = [
        ("summary_top_level", summary),
        ("summary_metrics", summary.get("metrics", {}) if isinstance(summary.get("metrics"), dict) else {}),
        ("summary_final", summary.get("final", {}) if isinstance(summary.get("final"), dict) else {}),
    ]
    for source_name, source in sources:
        if all(key in source for key in metric_keys):
            metrics = {key: _float_or_default(source.get(key)) for key in metric_keys}
            for key in optional_metric_keys:
                if key in source:
                    metrics[key] = _float_or_default(source.get(key))
            return metrics, source_name

    metrics = _compute_plc_npk_metrics_from_csv(run_dir)
    if metrics:
        return metrics, "computed_from_full_season_plc_timeseries_csv"
    return {}, "not_available"


def _extract_offline_npk_metrics(full_season_summary: dict[str, Any]) -> dict[str, Any]:
    stats = full_season_summary.get("stats", {})
    metrics = stats.get("npk_metrics", {}) if isinstance(stats, dict) else {}
    if not isinstance(metrics, dict) or not metrics:
        return {
            "npk_metrics_status": "not_available",
            "npk_source": "offline_root_zone_estimator",
            "reason": "full_season_sac summary does not contain N/P/K metrics",
        }
    return {
        "npk_metrics_status": metrics.get("npk_metrics_status", "offline_available"),
        "npk_source": metrics.get("npk_source", "offline_root_zone_estimator"),
        "metrics": metrics,
        "note": (
            "N/P/K values are offline root-zone estimates from the digital twin, "
            "not PLC HIL and not real nutrient sensor feedback."
        ),
    }


def _collect_plc_hil_npk_status() -> dict[str, Any]:
    base = RESULTS_ROOT / "full_season_plc"
    not_run = {
        "plc_hil_status": "not_run",
        "reason": "PLCSIM/TIA Portal environment not available or PLC HIL result not found",
    }
    if not base.exists():
        return not_run

    runs = sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.name)
    if not runs:
        return not_run

    run_dir = runs[-1]
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        return {
            **not_run,
            "result_dir": str(run_dir),
            "reason": "Latest full_season_plc result has no summary.json",
        }

    try:
        summary = _read_json(summary_path)
    except Exception as exc:
        return {
            **not_run,
            "result_dir": str(run_dir),
            "reason": f"Failed to read latest PLC summary: {exc}",
        }

    metrics, metrics_source = _extract_plc_npk_metrics(summary, run_dir)
    plc_enabled = bool(summary.get("plc_enabled", False))
    status = "completed" if plc_enabled else "not_run"
    reason = None if plc_enabled else (
        "Latest full_season_plc result is offline/simulation-only "
        "(plc_enabled=false); PLCSIM/TIA Portal environment not available or PLC HIL result not found"
    )
    payload: dict[str, Any] = {
        "plc_hil_status": status,
        "result_dir": str(run_dir),
        "summary": str(summary_path),
        "plc_enabled": plc_enabled,
        "plc_ok_rate": summary.get("plc_ok_rate"),
        "metrics_source": metrics_source,
        "metrics": metrics,
    }
    if reason:
        payload["reason"] = reason
    return payload


def _run_step(name: str, command: list[str]) -> None:
    """运行一个子脚本，失败时立即终止流水线。"""
    logger.info("")
    logger.info("=" * 72)
    logger.info("开始步骤: %s", name)
    logger.info("命令: %s", " ".join(command))
    logger.info("=" * 72)
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"{name} 失败，退出码: {result.returncode}")


def _train_stage(stage_name: str, timesteps: int | None) -> tuple[str, str]:
    """训练单个阶段 SAC 模型，返回阶段名和最终模型路径。

    这里用独立 Python 进程训练。多个阶段并行时，每个阶段互不共享模型参数，
    因此适合并行；后续全生育期仿真再按阶段加载对应模型。
    """
    train_command = [
        sys.executable,
        str(ROOT / "train_sac.py"),
        "--stage",
        stage_name,
        "--fresh",
    ]
    if timesteps is not None:
        train_command.extend(["--timesteps", str(timesteps)])
    _run_step(f"从头训练 SAC ({stage_name})", train_command)
    model_path = ROOT / "rl_models" / f"sac_{stage_name.lower()}_final"
    return stage_name, str(model_path) + ".zip"


def _train_stages(stages_to_train: list[str], timesteps: int | None, parallel: bool, max_workers: int) -> dict[str, str]:
    """训练一个或多个阶段；parallel=True 时并行启动多个训练进程。"""
    if not parallel or len(stages_to_train) <= 1:
        return dict(_train_stage(stage_name, timesteps) for stage_name in stages_to_train)

    workers = max(1, min(max_workers, len(stages_to_train)))
    logger.info("并行训练 SAC 阶段: %s (workers=%d)", ", ".join(stages_to_train), workers)
    trained_models: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_train_stage, stage_name, timesteps): stage_name
            for stage_name in stages_to_train
        }
        for future in as_completed(futures):
            stage_name, model_path = future.result()
            trained_models[stage_name] = model_path
            logger.info("阶段 %s 训练完成: %s", stage_name, model_path)
    return {stage: trained_models[stage] for stage in stages_to_train}


def _copy_image(src: str | Path | None, dst_dir: Path, filename: str) -> str | None:
    """复制一张图到流水线统一图片目录，返回复制后的路径。"""
    if not src:
        return None
    src_path = Path(src)
    if not src_path.exists():
        logger.warning("待汇总图片不存在，跳过: %s", src_path)
        return None
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst_path = dst_dir / filename
    shutil.copy2(src_path, dst_path)
    return str(dst_path)


def _collect_pipeline_images(pipeline_summary: dict[str, Any], image_dir: Path) -> dict[str, str]:
    """把本次流水线生成的关键图片复制到一个统一目录。"""
    copied: dict[str, str] = {}
    steps = pipeline_summary.get("steps", {})

    controllability_dir = steps.get("controllability", {}).get("result_dir")
    if controllability_dir:
        source = ROOT / "experiments" / "images" / "stock_solution_controllability" / Path(controllability_dir).name / "stock_solution_controllability.png"
        copied_path = _copy_image(source, image_dir, "01_stock_solution_controllability.png")
        if copied_path:
            copied["stock_solution_controllability"] = copied_path

    short_event_dir = steps.get("short_event_response", {}).get("result_dir")
    if short_event_dir:
        source = ROOT / "experiments" / "images" / "short_event_response" / Path(short_event_dir).name / "short_event_response.png"
        copied_path = _copy_image(source, image_dir, "02_short_event_response.png")
        if copied_path:
            copied["short_event_response"] = copied_path

    control_summary = steps.get("control_strategy_fixed_vs_sac", {}).get("summary", {})
    control_artifacts = control_summary.get("artifacts", {})
    control_images = [
        ("root_zone_ec_tracking", control_artifacts.get("root_zone_ec_png"), "03_root_zone_ec_tracking.png"),
        ("delivery_execution", control_artifacts.get("delivery_execution_png"), "04_delivery_execution.png"),
    ]
    for key, src, filename in control_images:
        copied_path = _copy_image(src, image_dir, filename)
        if copied_path:
            copied[key] = copied_path

    suite_summary = steps.get("simulation_suite", {}).get("summary", {})
    suite_artifacts = suite_summary.get("artifacts", {})
    suite_images = [
        ("irrigation_regime_t1_t2", suite_artifacts.get("irrigation_regime_png"), "05_irrigation_regime_t1_t2.png"),
    ]
    for key, src, filename in suite_images:
        copied_path = _copy_image(src, image_dir, filename)
        if copied_path:
            copied[key] = copied_path

    full_season_summary = steps.get("full_season_sac", {}).get("summary", {})
    full_season_artifacts = full_season_summary.get("artifacts", {})
    full_season_images = [
        ("full_season_root_zone_ec", full_season_artifacts.get("root_zone_ec_png"), "06_full_season_root_zone_ec.png"),
        ("full_season_delivery_execution", full_season_artifacts.get("delivery_execution_png"), "07_full_season_delivery_execution.png"),
        ("full_season_water_response", full_season_artifacts.get("water_response_png"), "08_full_season_water_response.png"),
    ]
    for key, src, filename in full_season_images:
        copied_path = _copy_image(src, image_dir, filename)
        if copied_path:
            copied[key] = copied_path

    eval_step = steps.get("eval_sac", {})
    eval_summary = eval_step.get("summary", {})
    eval_artifacts = eval_summary.get("artifacts", {})
    eval_png = eval_artifacts.get("png_path") or eval_artifacts.get("png")
    if eval_png and not Path(eval_png).is_absolute() and eval_step.get("result_dir"):
        eval_png = Path(eval_step["result_dir"]) / eval_png
    copied_path = _copy_image(eval_png, image_dir, "09_eval_sac.png")
    if copied_path:
        copied["eval_sac"] = copied_path

    return copied


def _check_controllability() -> tuple[Path, dict[str, Any]]:
    """运行可控域实验，并确认固定策略安全且存在目标控制区域。"""
    _run_step(
        "母液混合可控域",
        [sys.executable, str(ROOT / "experiments" / "run_stock_solution_controllability.py")],
    )
    run_dir = _latest_run_dir("stock_solution_controllability")
    summary = _read_json(run_dir / "summary.json")
    fixed = summary["fixed_strategy"]

    if fixed["ec_risk"] or fixed["ph_burn"]:
        raise RuntimeError(
            "固定策略未通过母液安全检查: "
            f"EC={fixed['ec_out_dS_m']:.3f}, pH={fixed['ph_out']:.3f}"
        )
    if summary["target_match_count"] <= 0:
        raise RuntimeError("当前动作范围内不存在满足配液设定 EC/pH 的可控区域。")

    logger.info(
        "可控域检查通过: 固定策略 EC=%.3f, pH=%.3f, 目标网格点=%d",
        fixed["ec_out_dS_m"],
        fixed["ph_out"],
        summary["target_match_count"],
    )
    return run_dir, summary


def _check_short_event() -> tuple[Path, dict[str, Any]]:
    """运行短期事件响应，并确认固定策略没有触发烧苗。"""
    _run_step(
        "短期单次灌溉事件响应",
        [sys.executable, str(ROOT / "experiments" / "run_short_event_response.py")],
    )
    run_dir = _latest_run_dir("short_event_response")
    summary = _read_json(run_dir / "summary.json")
    event = summary["short_event_response"]

    if event["stopped_by_safety"]:
        raise RuntimeError(
            "短期事件响应触发安全终止，停止训练。"
            f" EC 峰值={event['ec_peak']:.3f}"
        )

    logger.info(
        "短期事件检查通过: theta 峰值=%.4f, EC 峰值=%.3f, 灌溉量=%.2f mm",
        event["theta_peak"],
        event["ec_peak"],
        event["total_irrigation_mm"],
    )
    return run_dir, summary


def run_pipeline(args: argparse.Namespace) -> Path:
    """执行完整流水线并写入总 summary.json。"""
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    pipeline_dir = RESULTS_ROOT / "full_pipeline" / run_id
    pipeline_image_dir = ROOT / "experiments" / "images" / "full_pipeline" / run_id
    pipeline_dir.mkdir(parents=True, exist_ok=True)

    pipeline_summary: dict[str, Any] = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "running",
        "preflight_only": args.preflight_only,
        "acceptance_smoke": args.acceptance_smoke,
        "steps": {},
    }

    try:
        controllability_dir, controllability = _check_controllability()
        pipeline_summary["steps"]["controllability"] = {
            "result_dir": str(controllability_dir),
            "fixed_strategy": controllability["fixed_strategy"],
            "target_match_count": controllability["target_match_count"],
        }

        short_event_dir, short_event = _check_short_event()
        pipeline_summary["steps"]["short_event_response"] = {
            "result_dir": str(short_event_dir),
            "summary": short_event["short_event_response"],
        }
        pipeline_summary["steps"]["plc_hil_npk"] = _collect_plc_hil_npk_status()
        pipeline_summary["steps"]["npk_metrics"] = {
            "npk_metrics_status": "not_available",
            "npk_source": "offline_root_zone_estimator",
            "reason": "Full-season SAC step was not run yet.",
        }

        if args.preflight_only:
            pipeline_summary["status"] = "preflight_passed"
            pipeline_summary["image_dir"] = str(pipeline_image_dir)
            pipeline_summary["images"] = _collect_pipeline_images(pipeline_summary, pipeline_image_dir)
            return pipeline_dir

        stages_to_train = [args.stage] if args.single_stage else ["INI", "DEV", "MID", "LATE"]
        training_timesteps = 1000 if args.acceptance_smoke and args.timesteps is None else args.timesteps
        if args.acceptance_smoke:
            stages_to_train = ["INI", "DEV", "MID", "LATE"]
        trained_models = _train_stages(
            stages_to_train,
            training_timesteps,
            parallel=args.parallel_train,
            max_workers=args.train_workers,
        )

        primary_stage = args.stage if args.single_stage else "MID"
        model_path = ROOT / "rl_models" / f"sac_{primary_stage.lower()}_final"
        model_files_exist = {stage: Path(path).exists() for stage, path in trained_models.items()}
        if args.acceptance_smoke:
            training_mode = "four_stage_smoke"
            strict_acceptance: bool | str = "software_pipeline_only"
        elif args.single_stage:
            training_mode = "single_stage_smoke" if training_timesteps is not None else "single_stage_full"
            strict_acceptance = False
        else:
            training_mode = "four_stage_smoke" if training_timesteps is not None else "full"
            strict_acceptance = "software_pipeline_only" if training_timesteps is not None else True
        pipeline_summary["steps"]["train_sac"] = {
            "stages": stages_to_train,
            "trained_stages": stages_to_train,
            "models": trained_models,
            "model_files": trained_models,
            "model_files_exist_by_stage": model_files_exist,
            "model_files_exist": all(model_files_exist.values()),
            "timesteps_per_stage": training_timesteps,
            "training_mode": training_mode,
            "strict_acceptance": strict_acceptance,
            "quality_note": (
                "Smoke training validates the software pipeline only; it is not evidence of an optimal SAC policy."
                if training_timesteps is not None else
                "Full training mode uses the configured SAC timesteps."
            ),
            "primary_stage_for_control_plot": primary_stage,
            "parallel_train": args.parallel_train,
            "train_workers": args.train_workers,
        }

        _run_step(
            "水肥控制策略对比：固定策略 vs SAC",
            [
                sys.executable,
                str(ROOT / "experiments" / "run_control_strategy_fixed_vs_sac.py"),
                "--stage",
                primary_stage,
                "--model",
                str(model_path),
                "--continuous-control",
            ],
        )
        control_strategy_dir = _latest_run_dir("control_strategy_fixed_vs_sac")
        pipeline_summary["steps"]["control_strategy_fixed_vs_sac"] = {
            "result_dir": str(control_strategy_dir),
            "summary": _read_json(control_strategy_dir / "summary.json"),
        }

        _run_step(
            "全生育期 SAC 控制策略仿真",
            [
                sys.executable,
                str(ROOT / "experiments" / "run_full_season_sac.py"),
                "--irrigation-regime",
                "T2",
                "--dt-min",
                str(args.simulation_dt_min),
            ] + (["--model", str(model_path)] if args.single_stage else []),
        )
        full_season_dir = _latest_run_dir("full_season_sac")
        full_season_summary = _read_json(full_season_dir / "summary.json")
        pipeline_summary["steps"]["full_season_sac"] = {
            "result_dir": str(full_season_dir),
            "summary": full_season_summary,
        }
        pipeline_summary["steps"]["npk_metrics"] = _extract_offline_npk_metrics(full_season_summary)

        _run_step(
            "SAC 完整生育期评估",
            [
                sys.executable,
                str(ROOT / "eval_sac.py"),
                "--dt-min",
                str(args.simulation_dt_min),
            ] + (["--model", str(model_path)] if args.single_stage else []),
        )
        eval_dir = _latest_run_dir("eval_sac")
        pipeline_summary["steps"]["eval_sac"] = {
            "model": str(model_path) + ".zip" if args.single_stage else None,
            "model_dir": str(ROOT / "rl_models") if not args.single_stage else None,
            "result_dir": str(eval_dir),
            "summary": _read_json(eval_dir / "summary.json"),
        }

        _run_step(
            "T1/T2 灌溉制度季节对比",
            [sys.executable, str(ROOT / "experiments" / "run_simulation_suite.py")],
        )
        suite_dir = _latest_run_dir("simulation_suite")
        pipeline_summary["steps"]["simulation_suite"] = {
            "result_dir": str(suite_dir),
            "summary": _read_json(suite_dir / "summary.json"),
        }

        pipeline_summary["status"] = "completed"
        pipeline_summary["image_dir"] = str(pipeline_image_dir)
        pipeline_summary["images"] = _collect_pipeline_images(pipeline_summary, pipeline_image_dir)
        return pipeline_dir
    except Exception as exc:
        pipeline_summary["status"] = "failed"
        pipeline_summary["error"] = str(exc)
        raise
    finally:
        (pipeline_dir / "summary.json").write_text(
            json.dumps(pipeline_summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("流水线汇总保存至: %s", pipeline_dir / "summary.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行数字孪生 SAC 完整实验流水线。")
    parser.add_argument("--stage", default="MID", choices=["INI", "DEV", "MID", "LATE"])
    parser.add_argument("--timesteps", type=int, default=None, help="覆盖 YAML 中的 SAC 总训练步数。")
    parser.add_argument(
        "--single-stage",
        action="store_true",
        help="只训练 --stage 指定的单个阶段；默认会依次训练 INI/DEV/MID/LATE 四个阶段。",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="只运行母液可控域和短期事件安全检查，不启动 SAC 训练。",
    )
    parser.add_argument(
        "--acceptance-smoke",
        action="store_true",
        help="验收烟测模式：按小步数依次训练 INI/DEV/MID/LATE，只证明软件链路完整。",
    )
    parser.add_argument(
        "--simulation-dt-min",
        type=float,
        default=5.0,
        help="流水线内全生育期仿真和 eval_sac 的步长；默认 5min 可解析 pipe.tau=8min 延迟。",
    )
    parser.add_argument(
        "--parallel-train",
        action="store_true",
        help="并行训练多个生育阶段 SAC 模型；默认仍按顺序训练。",
    )
    parser.add_argument(
        "--train-workers",
        type=int,
        default=4,
        help="--parallel-train 时最多同时启动的训练进程数。",
    )
    args = parser.parse_args()
    if args.acceptance_smoke and args.single_stage:
        parser.error("--acceptance-smoke trains all four stages and cannot be combined with --single-stage.")
    return args


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    output_dir = run_pipeline(parse_args())
    logger.info("流水线完成: %s", output_dir)
