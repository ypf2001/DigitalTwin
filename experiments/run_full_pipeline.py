"""数字孪生 SAC 实验一键流水线。

执行顺序：
1. 母液混合可控域实验；
2. 短期单次灌溉事件响应；
3. 从头训练 SAC；
4. 固定策略与 SAC 离线对比；
5. SAC 完整生育期评估；
6. 固定策略短期仿真与 T1/T2 季节对比。

前两步是安全门。若固定策略不在安全区域，或短期事件触发烧苗，
流水线会立即停止，避免使用错误配置训练 SAC。
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = ROOT / "results"
logger = logging.getLogger(__name__)


def _latest_run_dir(experiment_name: str) -> Path:
    """返回指定实验最近生成的时间戳目录。"""
    base = RESULTS_ROOT / experiment_name
    runs = sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.name)
    if not runs:
        raise RuntimeError(f"实验没有生成结果目录: {base}")
    return runs[-1]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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
        raise RuntimeError("当前动作范围内不存在满足目标 EC/pH 的可控区域。")

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
    pipeline_dir.mkdir(parents=True, exist_ok=True)

    pipeline_summary: dict[str, Any] = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "running",
        "preflight_only": args.preflight_only,
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

        if args.preflight_only:
            pipeline_summary["status"] = "preflight_passed"
            return pipeline_dir

        train_command = [
            sys.executable,
            str(ROOT / "train_sac.py"),
            "--stage",
            args.stage,
            "--fresh",
        ]
        if args.timesteps is not None:
            train_command.extend(["--timesteps", str(args.timesteps)])
        _run_step("从头训练 SAC", train_command)

        model_path = ROOT / "rl_models" / f"sac_{args.stage.lower()}_final"
        pipeline_summary["steps"]["train_sac"] = {"model": str(model_path) + ".zip"}

        _run_step(
            "固定策略与 SAC 对比",
            [
                sys.executable,
                str(ROOT / "experiments" / "run_fixed_vs_sac.py"),
                "--stage",
                args.stage,
                "--model",
                str(model_path),
                "--continuous-control",
            ],
        )
        fixed_vs_sac_dir = _latest_run_dir("fixed_vs_sac")
        pipeline_summary["steps"]["fixed_vs_sac"] = {
            "result_dir": str(fixed_vs_sac_dir),
            "summary": _read_json(fixed_vs_sac_dir / "summary.json"),
        }

        _run_step(
            "SAC 完整生育期评估",
            [
                sys.executable,
                str(ROOT / "eval_sac.py"),
                "--model",
                str(model_path),
            ],
        )
        pipeline_summary["steps"]["eval_sac"] = {"model": str(model_path) + ".zip"}

        _run_step(
            "固定策略与 T1/T2 季节实验",
            [sys.executable, str(ROOT / "experiments" / "run_simulation_suite.py")],
        )
        suite_dir = _latest_run_dir("simulation_suite")
        pipeline_summary["steps"]["simulation_suite"] = {
            "result_dir": str(suite_dir),
            "summary": _read_json(suite_dir / "summary.json"),
        }

        pipeline_summary["status"] = "completed"
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
        "--preflight-only",
        action="store_true",
        help="只运行母液可控域和短期事件安全检查，不启动 SAC 训练。",
    )
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    output_dir = run_pipeline(parse_args())
    logger.info("流水线完成: %s", output_dir)
