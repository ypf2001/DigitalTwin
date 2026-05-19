"""
训练监控看板 — dashboard.py
============================
持续监控 EvalCallback 写入的 evaluations.npz，以动态刷新的方式
展示 SAC 训练进度。

用法：
    python dashboard.py
    python dashboard.py --interval 1.5    # 自定义刷新间隔（秒）
"""

import os
import sys
import time
import argparse
import numpy as np

# Windows GBK 编码修复
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 固定路径（与 train_sac.py 中 EvalCallback 的 log_path 一致）
EVAL_PATH = os.path.join(os.path.dirname(__file__), "rl_logs", "evaluations.npz")


def clear_screen():
    """跨平台清屏。"""
    os.system("cls" if os.name == "nt" else "clear")


def load_eval_data(filepath: str):
    """安全加载 .npz 文件，返回 (timesteps, results, ep_lengths) 或 None。"""
    try:
        data = np.load(filepath)
        timesteps = data["timesteps"]        # shape (N,)
        results = data["results"]            # shape (N, n_episodes)
        ep_lengths = data["ep_lengths"]      # shape (N, n_episodes)
        data.close()
        return timesteps, results, ep_lengths
    except (OSError, ValueError, KeyError, EOFError):
        # 文件被训练进程锁死 / 写入不完整 / 损坏 → 静默跳过
        return None


def format_trend(current: float, previous: float) -> str:
    """比较当前值和上一值，返回趋势箭头。"""
    if previous is None:
        return "  —"
    delta = current - previous
    if delta > 1e-4:
        return f"  ↑ (+{delta:.4f})"
    elif delta < -1e-4:
        return f"  ↓ ({delta:.4f})"
    else:
        return "  → (0)"


def print_header():
    """打印看板标题栏。"""
    print("=" * 62)
    print("  🌱  马铃薯水肥数字孪生 — SAC 训练监控看板")
    print("=" * 62)


def print_status(last_eval_count: int, file_mtime: float):
    """打印文件状态行。"""
    status = "● 监控中" if last_eval_count > 0 else "○ 等待首次评估..."
    mtime_str = time.strftime("%H:%M:%S", time.localtime(file_mtime)) if file_mtime else "--:--:--"
    print(f"  状态: {status}    文件更新时间: {mtime_str}")
    print("-" * 62)


def main(interval: float = 2.0):
    """主循环：持续监控 evaluations.npz，每次检测到更新就刷新看板。"""
    prev_eval_count = 0          # 上一次检测到的评估次数
    prev_avg_rewards = None      # shape (N,) 的上一次数据，用于趋势对比
    best_reward = None           # 历史最佳（单次评估的平均奖励）
    best_timestep = None         # 历史最佳对应的训练步数
    last_mtime = None            # 文件修改时间

    while True:
        # ---- 1. 检查文件是否存在 ----
        if not os.path.exists(EVAL_PATH):
            clear_screen()
            print_header()
            print(f"\n  ⏳ 等待评估文件生成...\n  {EVAL_PATH}\n")
            print("-" * 62)
            print("  按 Ctrl+C 退出")
            time.sleep(interval)
            continue

        # ---- 2. 检测文件是否更新 ----
        current_mtime = os.path.getmtime(EVAL_PATH)
        file_changed = (last_mtime is None) or (current_mtime > last_mtime + 0.1)

        if not file_changed:
            time.sleep(interval)
            continue

        # ---- 3. 安全加载数据 ----
        loaded = load_eval_data(EVAL_PATH)
        if loaded is None:
            time.sleep(interval)
            continue

        timesteps, results, ep_lengths = loaded
        last_mtime = current_mtime

        # ---- 4. 计算指标 ----
        n_evals = len(timesteps)                          # 当前评估总次数
        avg_per_eval = results.mean(axis=1)                # 每次评估的平均奖励 (N,)
        latest_avg = avg_per_eval[-1]                      # 最新一次的平均奖励
        latest_timestep = timesteps[-1]                    # 最新评估对应的训练步数

        # 历史最佳（仅在新数据出现时更新）
        best_idx = np.argmax(avg_per_eval)
        best_reward = avg_per_eval[best_idx]
        best_timestep = timesteps[best_idx]

        # 趋势对比
        if prev_avg_rewards is not None and n_evals > prev_eval_count:
            prev_avg = avg_per_eval[-2]  # 上一次评估的平均奖励
        else:
            prev_avg = None

        # ---- 5. 清屏并绘制看板 ----
        clear_screen()
        print_header()

        # 文件状态
        mtime_str = time.strftime("%H:%M:%S", time.localtime(current_mtime))
        print(f"  评估次数: {n_evals}    文件更新: {mtime_str}    刷新间隔: {interval}s")
        print("-" * 62)

        # 训练进度
        progress_pct = timesteps[-1] / 200000 * 100 if len(timesteps) > 0 else 0
        print(f"\n  📊 训练进度")
        print(f"     当前步数: {latest_timestep:,} / 200,000 ({progress_pct:.1f}%)")

        # 奖励指标
        print(f"\n  🎯 奖励指标")
        print(f"     历史最佳平均奖励:  {best_reward:12.4f}  (第 {best_timestep:,} 步)")
        print(f"     最新平均奖励:      {latest_avg:12.4f}{format_trend(latest_avg, prev_avg)}")

        # 最近一次评估的详细结果
        print(f"\n  📋 最新评估详情 (步数 {latest_timestep:,})")
        latest_episodes = results[-1]
        print(f"     {'Episode':<12}{'奖励':>12}{'步长':>10}")
        print(f"     {'-' * 34}")
        for i in range(len(latest_episodes)):
            print(f"     {i + 1:<12}{latest_episodes[i]:>12.4f}{ep_lengths[-1, i]:>10}")

        # 历史最佳评估的详细结果
        if best_idx != n_evals - 1:
            print(f"\n  🏆 历史最佳评估详情 (步数 {best_timestep:,})")
            best_episodes = results[best_idx]
            for i in range(len(best_episodes)):
                print(f"     {i + 1:<12}{best_episodes[i]:>12.4f}{ep_lengths[best_idx, i]:>10}")

        # 最近 5 次评估趋势（简易 ASCII 折线）
        if n_evals >= 2:
            recent_n = min(n_evals, 6)
            recent_avgs = avg_per_eval[-recent_n:]
            recent_steps = timesteps[-recent_n:]
            print(f"\n  📈 最近 {recent_n} 次评估趋势")
            print(f"     {'步数':<10} {'平均奖励':>10}")
            print(f"     {'-' * 22}")
            for step, avg in zip(recent_steps, recent_avgs):
                bar = "█" * max(1, int((avg - avg_per_eval.min()) /
                                       (avg_per_eval.max() - avg_per_eval.min() + 1e-6) * 20))
                print(f"     {step:<10,} {avg:>10.4f}  {bar}")

        # 底部
        print("\n" + "-" * 62)
        print("  按 Ctrl+C 退出")
        print("=" * 62)

        # 更新状态，等待下一次检测
        prev_eval_count = n_evals
        prev_avg_rewards = avg_per_eval.copy()

        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SAC 训练监控看板")
    parser.add_argument("--interval", "-i", type=float, default=2.0,
                        help="刷新间隔（秒），默认 2.0")
    args = parser.parse_args()

    try:
        main(interval=args.interval)
    except KeyboardInterrupt:
        clear_screen()
        print("=" * 62)
        print("  监控已停止，再见！")
        print("=" * 62)
