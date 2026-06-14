# scripts/train_all_stages_until_best_shutdown.py
# 功能：依次训练 INI / DEV / MID / LATE 四个阶段，全部完成后可选自动关机。
#
# 用法示例：
#   python scripts/train_all_stages_until_best_shutdown.py
#   python scripts/train_all_stages_until_best_shutdown.py --shutdown
#   python scripts/train_all_stages_until_best_shutdown.py --chunk-steps 20000 --max-rounds 50 --patience 6 --shutdown

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STAGES = ["INI", "DEV", "MID", "LATE"]


def run_stage(args: argparse.Namespace, stage: str) -> int:
    """Run train_sac_until_best_shutdown.py for one growth stage."""
    cmd = [
        args.python,
        str(ROOT / "scripts" / "train_sac_until_best_shutdown.py"),
        "--stage",
        stage,
        "--chunk-steps",
        str(args.chunk_steps),
        "--max-rounds",
        str(args.max_rounds),
        "--patience",
        str(args.patience),
        "--min-improve",
        str(args.min_improve),
        "--start-total-steps",
        str(args.start_total_steps),
    ]

    if args.fresh:
        cmd.append("--fresh")

    print("\n" + "=" * 80)
    print(f"开始训练阶段：{stage}")
    print("=" * 80)
    print(">>>", " ".join(cmd), flush=True)

    return subprocess.run(cmd, cwd=ROOT).returncode


def shutdown_windows(delay_seconds: int = 60) -> None:
    """
    Shut down Windows after all stages are completed.

    To cancel during the countdown, run: shutdown /a
    """
    print(f"\n全部阶段训练完成，电脑将在 {delay_seconds} 秒后关机。")
    print("取消关机请输入：shutdown /a")
    os.system(f"shutdown /s /t {delay_seconds}")


def main() -> int:
    parser = argparse.ArgumentParser(description="依次训练 SAC 四个生育阶段，完成后可选自动关机。")

    parser.add_argument("--chunk-steps", type=int, default=20000, help="每轮增加训练步数")
    parser.add_argument("--max-rounds", type=int, default=50, help="每个阶段最大训练轮数")
    parser.add_argument("--patience", type=int, default=6, help="每个阶段连续未提升多少轮后停止")
    parser.add_argument("--min-improve", type=float, default=0.001, help="最小奖励提升阈值")
    parser.add_argument("--start-total-steps", type=int, default=120000, help="每个阶段第一轮目标总步数")
    parser.add_argument("--fresh", action="store_true", help="每个阶段第一轮都从头训练；一般不要开，除非重训")
    parser.add_argument("--shutdown", action="store_true", help="四个阶段全部训练完成后自动关机")
    parser.add_argument("--shutdown-delay", type=int, default=60, help="关机延迟秒数")
    parser.add_argument("--python", default=sys.executable, help="Python 解释器路径")

    args = parser.parse_args()

    for stage in STAGES:
        ret = run_stage(args, stage)
        if ret != 0:
            print(f"\n[ERROR] 阶段 {stage} 训练失败，退出码：{ret}")
            print("不会执行关机。")
            return ret

    print("\n" + "=" * 80)
    print("四个阶段 SAC 模型全部训练完成。")
    print("模型位置：")
    print("  rl_models/sac_ini_final.zip")
    print("  rl_models/sac_dev_final.zip")
    print("  rl_models/sac_mid_final.zip")
    print("  rl_models/sac_late_final.zip")
    print("=" * 80)

    if args.shutdown:
        shutdown_windows(args.shutdown_delay)
    else:
        print("\n未启用自动关机。需要关机请加：--shutdown")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
