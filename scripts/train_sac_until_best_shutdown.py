# scripts/train_sac_until_best_shutdown.py
# 功能：持续训练 SAC，直到评估奖励长期不再提升，然后可选自动关机。
#
# 用法示例：
#   python scripts/train_sac_until_best_shutdown.py --stage MID
#   python scripts/train_sac_until_best_shutdown.py --stage MID --shutdown
#   python scripts/train_sac_until_best_shutdown.py --stage MID --patience 6 --chunk-steps 20000 --max-rounds 50 --shutdown

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def run_cmd(cmd: list[str]) -> int:
    """Run a command from the project root and return its exit code."""
    print("\n>>>", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT).returncode


def load_best_eval_reward(stage: str) -> float | None:
    """
    Read the best evaluation reward from rl_logs/<stage>/evaluations.npz.

    Stable-Baselines3 EvalCallback writes evaluation results to this file.
    The larger the reward, the better the current SAC policy is considered.
    """
    stage_tag = stage.lower()
    eval_path = ROOT / "rl_logs" / stage_tag / "evaluations.npz"

    if not eval_path.exists():
        return None

    data = np.load(eval_path)
    if "results" not in data:
        return None

    results = data["results"]
    if len(results) == 0:
        return None

    mean_rewards = results.mean(axis=1)
    return float(np.max(mean_rewards))


def copy_best_model(stage: str, out_dir: Path) -> None:
    """Backup the current best_model.zip and final model to the run directory."""
    stage_tag = stage.lower()

    best_model = ROOT / "rl_models" / f"best_{stage_tag}" / "best_model.zip"
    final_model = ROOT / "rl_models" / f"sac_{stage_tag}_final.zip"

    out_dir.mkdir(parents=True, exist_ok=True)

    if best_model.exists():
        shutil.copy2(best_model, out_dir / f"sac_{stage_tag}_best_model.zip")

    if final_model.exists():
        shutil.copy2(final_model, out_dir / f"sac_{stage_tag}_final.zip")


def shutdown_windows(delay_seconds: int = 60) -> None:
    """
    Shut down Windows after delay_seconds.

    To cancel during the countdown, run: shutdown /a
    """
    print(f"\n系统将在 {delay_seconds} 秒后关机。取消关机请输入：shutdown /a")
    os.system(f"shutdown /s /t {delay_seconds}")


def main() -> int:
    parser = argparse.ArgumentParser(description="持续训练 SAC，直到评估奖励不再提升，然后可选自动关机。")

    parser.add_argument("--stage", default="MID", choices=["INI", "DEV", "MID", "LATE"], help="训练哪个生育阶段模型")
    parser.add_argument("--chunk-steps", type=int, default=20000, help="每一轮增加训练步数")
    parser.add_argument("--max-rounds", type=int, default=50, help="最多训练轮数，防止无限训练")
    parser.add_argument("--patience", type=int, default=6, help="连续多少轮没有明显提升就停止")
    parser.add_argument("--min-improve", type=float, default=1e-3, help="奖励提升小于该值视为没有提升")
    parser.add_argument("--start-total-steps", type=int, default=120000, help="第一轮目标总步数")
    parser.add_argument("--shutdown", action="store_true", help="训练结束后自动关机")
    parser.add_argument("--shutdown-delay", type=int, default=60, help="关机延迟秒数")
    parser.add_argument("--fresh", action="store_true", help="第一轮是否从头训练；一般不要开，除非想重训")
    parser.add_argument("--python", default=sys.executable, help="Python 解释器路径")

    args = parser.parse_args()

    stage = args.stage.upper()
    stage_tag = stage.lower()

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_dir = ROOT / "results" / "sac_until_best" / f"{stage_tag}_{run_id}"
    result_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("SAC 持续训练脚本")
    print(f"阶段: {stage}")
    print(f"每轮增加步数: {args.chunk_steps}")
    print(f"最大轮数: {args.max_rounds}")
    print(f"耐心轮数 patience: {args.patience}")
    print(f"最小提升 min_improve: {args.min_improve}")
    print(f"结果目录: {result_dir}")
    print("=" * 70)

    best_reward = -float("inf")
    best_round = 0
    no_improve_rounds = 0
    history: list[dict] = []

    for round_idx in range(1, args.max_rounds + 1):
        target_steps = args.start_total_steps + (round_idx - 1) * args.chunk_steps

        cmd = [
            args.python,
            str(ROOT / "train_sac.py"),
            "--stage",
            stage,
            "--timesteps",
            str(target_steps),
            "--resume",
        ]

        if args.fresh and round_idx == 1:
            cmd = [
                args.python,
                str(ROOT / "train_sac.py"),
                "--stage",
                stage,
                "--timesteps",
                str(target_steps),
                "--fresh",
            ]

        print("\n" + "=" * 70)
        print(f"第 {round_idx}/{args.max_rounds} 轮训练")
        print(f"目标总步数: {target_steps}")
        print("=" * 70)

        ret = run_cmd(cmd)

        if ret != 0:
            print(f"[ERROR] train_sac.py 退出码异常: {ret}")
            print("停止训练，不执行关机。")
            return ret

        current_reward = load_best_eval_reward(stage)

        if current_reward is None:
            print("[WARN] 没有读取到 evaluations.npz，暂时无法判断是否最优。")
            current_reward = -float("inf")

        improved = current_reward > best_reward + args.min_improve

        if improved:
            best_reward = current_reward
            best_round = round_idx
            no_improve_rounds = 0
            copy_best_model(stage, result_dir)
            print(f"[BEST] 奖励提升: best_reward = {best_reward:.6f}")
        else:
            no_improve_rounds += 1
            print(f"[NO IMPROVE] 当前最好奖励 = {current_reward:.6f}")
            print(f"连续未提升轮数: {no_improve_rounds}/{args.patience}")

        row = {
            "round": round_idx,
            "target_total_steps": target_steps,
            "current_best_eval_reward": current_reward,
            "global_best_reward": best_reward,
            "best_round": best_round,
            "improved": improved,
            "no_improve_rounds": no_improve_rounds,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        history.append(row)

        with (result_dir / "training_history.json").open("w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

        with (result_dir / "latest_status.json").open("w", encoding="utf-8") as f:
            json.dump(row, f, ensure_ascii=False, indent=2)

        if no_improve_rounds >= args.patience:
            print("\n" + "=" * 70)
            print("评估奖励已经连续多轮没有明显提升，认为已接近当前最优。")
            print(f"最佳轮次: {best_round}")
            print(f"最佳奖励: {best_reward:.6f}")
            print(f"结果目录: {result_dir}")
            print("=" * 70)
            break

        time.sleep(3)

    copy_best_model(stage, result_dir)

    print("\n训练结束。")
    print(f"最佳模型备份目录: {result_dir}")
    print(f"原始 best_model 位置: rl_models/best_{stage_tag}/best_model.zip")
    print(f"原始 final 模型位置: rl_models/sac_{stage_tag}_final.zip")

    if args.shutdown:
        shutdown_windows(args.shutdown_delay)
    else:
        print("\n未启用自动关机。需要自动关机请加参数：--shutdown")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
