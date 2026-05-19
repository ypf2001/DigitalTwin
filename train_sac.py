"""
SAC 训练脚本 — train_sac.py
============================
用 Stable-Baselines3 SAC 训练施肥灌溉控制器。
使用 DigitalTwinGymEnv（Gymnasium 标准封装）。

用法：
    python train_sac.py
    python train_sac.py --timesteps 200000 --stage BULKING
"""

import argparse
import os
import sys
import numpy as np

# Windows 键盘检测
if os.name == "nt":
    import msvcrt
else:
    msvcrt = None

from digital_twin_gym_env import DigitalTwinGymEnv

try:
    from stable_baselines3 import SAC
    from stable_baselines3.common.callbacks import (
        EvalCallback,
        CheckpointCallback,
        BaseCallback,
    )
    from stable_baselines3.common.monitor import Monitor
except ImportError:
    print("[ERROR] 请安装 stable-baselines3: pip install stable-baselines3")
    sys.exit(1)


class KeyboardStopCallback(BaseCallback):
    """每步检测键盘输入：按 q 或 Esc 优雅停止训练。"""
    def _on_step(self):
        if msvcrt is not None and msvcrt.kbhit():
            key = msvcrt.getch()
            if key in (b"q", b"Q", b"\x1b"):
                print("\n[检测到按键，正在优雅停止...]")
                return False
        return True

def make_env(stage_name: str, dt_min: float = 60.0,
             obs_noise: float = 0.01, reward_scale: float = 0.1):
    """创建环境的工厂函数。"""
    def _init():
        env = DigitalTwinGymEnv(
            growth_stage=stage_name,
            area_ha=0.1,
            dt_min=dt_min,
            ep_len_days=5.0,
            et0_mm_day=5.0,
            obs_noise_std=obs_noise,
            reward_scale=reward_scale,
        )
        return env
    return _init


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SAC 训练")
    parser.add_argument("--timesteps", type=int, default=200000,
                        help="总训练步数")
    parser.add_argument("--stage", type=str, default="BULKING",
                        choices=["INI", "DEV", "MID", "LATE",
                                 "EMERGENCE", "VEGETATIVE", "TUBER_INIT",
                                 "BULKING", "STARCH_ACCUMULATION", "MATURATION"])
    parser.add_argument("--save-dir", type=str, default="./rl_models")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    os.makedirs(args.save_dir, exist_ok=True)

    # 确保 rl_logs 目录存在（dashboard 从这里读取 evaluations.npz）
    rl_logs_dir = os.path.join(os.path.dirname(__file__), "rl_logs")
    os.makedirs(rl_logs_dir, exist_ok=True)

    # 阶段名映射到简写
    stage_short = args.stage
    full_to_short = {
        "EMERGENCE": "INI", "VEGETATIVE": "DEV",
        "TUBER_INIT": "DEV", "BULKING": "MID",
        "STARCH_ACCUMULATION": "LATE", "MATURATION": "LATE",
    }
    if args.stage in full_to_short:
        stage_short = full_to_short[args.stage]
    model_tag = stage_short.lower()

    print("=" * 60)
    print(f"SAC 训练 - 生育阶段: {args.stage} (简写: {stage_short})")
    print(f"总步数: {args.timesteps}")
    print("=" * 60)

    # ---- 创建环境（SAC 不需要 VecNormalize） ----
    train_env = make_env(stage_short, obs_noise=0.01)()
    eval_env = make_env(stage_short, obs_noise=0.0)()

    # ---- SAC 模型 ----
    model = SAC(
        "MlpPolicy",
        train_env,
        learning_rate=3e-4,
        buffer_size=100000,
        batch_size=256,
        learning_starts=1000,
        tau=0.005,
        gamma=0.99,
        ent_coef='auto',
        verbose=1,
        seed=args.seed,
    )

    # ---- 回调 ----
    keyboard_cb = KeyboardStopCallback()
    checkpoint_cb = CheckpointCallback(
        save_freq=max(5000, args.timesteps // 20),
        save_path=args.save_dir,
        name_prefix=f"sac_{model_tag}",
    )
    # 用 Monitor 包裹评估环境（避免 EvalCallback 警告）
    eval_env_mon = Monitor(eval_env)
    eval_cb = EvalCallback(
        eval_env_mon,
        best_model_save_path=args.save_dir,
        log_path=rl_logs_dir,
        eval_freq=2000,
        deterministic=True,
        n_eval_episodes=5,
    )

    # ---- 训练 ----
    print(f"\n开始训练... (按 q 键优雅停止)\n")
    try:
        model.learn(
            total_timesteps=args.timesteps,
            callback=[keyboard_cb, checkpoint_cb, eval_cb],
        )
    except KeyboardInterrupt:
        print("\n\n[中断] 用户按下 Ctrl+C，正在保存当前模型...")

    # ---- 保存最终模型（正常结束或中断都会执行） ----
    final_path = os.path.join(args.save_dir, f"sac_{model_tag}_final")
    model.save(final_path)
    print(f"\n[OK] SAC 模型已保存: {final_path}.zip")
