"""
PPO 训练脚本 — train_ppo.py
============================
用 Stable-Baselines3 PPO 训练施肥灌溉控制器。
使用 DigitalTwinGymEnv（Gymnasium 标准封装）。

用法：
    python train_ppo.py
    python train_ppo.py --timesteps 200000 --stage BULKING
"""

import argparse
import os
import sys
import numpy as np

from digital_twin_gym_env import DigitalTwinGymEnv

try:
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import (
        EvalCallback,
        CheckpointCallback,
        BaseCallback,
    )
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize
except ImportError:
    print("[ERROR] 请安装 stable-baselines3: pip install stable-baselines3")
    sys.exit(1)

STOP_FILE = os.path.join(os.path.dirname(__file__), "stop_training")

class StopFileCallback(BaseCallback):
    """检测项目目录下是否有 `stop_training` 文件，有则优雅停止训练。"""
    def _on_step(self):
        if os.path.exists(STOP_FILE):
            print("\n[检测到 stop_training 文件，正在优雅停止...]")
            os.remove(STOP_FILE)
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
    parser = argparse.ArgumentParser(description="PPO 训练")
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
    print(f"PPO 训练 - 生育阶段: {args.stage} (简写: {stage_short})")
    print(f"总步数: {args.timesteps}")
    print("=" * 60)

    # ---- 创建向量化环境 ----
    train_env = DummyVecEnv([make_env(stage_short, obs_noise=0.01)])
    eval_env = DummyVecEnv([make_env(stage_short, obs_noise=0.0)])

    # VecNormalize: 只对 reward 归一化 (obs 已在 GymEnv 里归一化)
    train_env = VecNormalize(
        train_env, training=True, norm_obs=False, norm_reward=True,
        clip_obs=10.0, clip_reward=10.0,
    )
    eval_env = VecNormalize(
        eval_env, training=False, norm_obs=False, norm_reward=True,
        clip_obs=10.0, clip_reward=10.0,
    )

    # ---- PPO 模型 ----
    model = PPO(
        "MlpPolicy",
        train_env,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.01,
        vf_coef=0.5,
        max_grad_norm=0.5,
        verbose=1,
        # tensorboard_log 未安装时注释掉
        # tensorboard_log="./tb_logs/",
        seed=args.seed,
    )

    # ---- 回调 ----
    stop_cb = StopFileCallback()
    checkpoint_cb = CheckpointCallback(
        save_freq=max(5000, args.timesteps // 20),
        save_path=args.save_dir,
        name_prefix=f"ppo_{model_tag}",
    )
    eval_cb = EvalCallback(
        eval_env,
        best_model_save_path=args.save_dir,
        log_path="./rl_logs/",
        eval_freq=max(2000, args.timesteps // 50),
        deterministic=True,
        n_eval_episodes=3,
    )

    # ---- 训练 ----
    print(f"\n开始训练... (停止方法: 在项目目录新建文件 {STOP_FILE} 即可优雅停止)\n")
    try:
        model.learn(
            total_timesteps=args.timesteps,
            callback=[stop_cb, checkpoint_cb, eval_cb],
            progress_bar=True,
        )
    except KeyboardInterrupt:
        print("\n\n[中断] 用户按下 Ctrl+C，正在保存当前模型...")

    # ---- 保存最终模型（正常结束或中断都会执行） ----
    final_path = os.path.join(args.save_dir, f"ppo_{model_tag}_final")
    model.save(final_path)
    train_env.save(os.path.join(args.save_dir, f"vec_normalize_{model_tag}.pkl"))
    print(f"\n[OK] 模型已保存: {final_path}.zip")
