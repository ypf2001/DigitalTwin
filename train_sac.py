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
import logging
import os
import sys
import numpy as np

logger = logging.getLogger("train_sac")

# Windows 键盘检测
if os.name == "nt":
    import msvcrt
else:
    msvcrt = None

from digital_twin_gym_env import DigitalTwinGymEnv
from config_loader import load_config

try:
    from stable_baselines3 import SAC
    from stable_baselines3.common.callbacks import (
        EvalCallback,
        CheckpointCallback,
        BaseCallback,
    )
    from stable_baselines3.common.monitor import Monitor
except ImportError:
    logger.error("请安装 stable-baselines3: pip install stable-baselines3")
    sys.exit(1)


class KeyboardStopCallback(BaseCallback):
    """每步检测键盘输入：按 q 或 Esc 优雅停止训练。"""
    def _on_step(self):
        if msvcrt is not None and msvcrt.kbhit():
            key = msvcrt.getch()
            if key in (b"q", b"Q", b"\x1b"):
                logger.info("检测到按键，正在优雅停止...")
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
    sac_cfg = load_config().sac()

    parser = argparse.ArgumentParser(description="SAC 训练")
    parser.add_argument("--timesteps", type=int, default=sac_cfg["total_timesteps"],
                        help="总训练步数")
    parser.add_argument("--stage", type=str, default="BULKING",
                        choices=["INI", "DEV", "MID", "LATE",
                                 "EMERGENCE", "VEGETATIVE", "TUBER_INIT",
                                 "BULKING", "STARCH_ACCUMULATION", "MATURATION"])
    parser.add_argument("--save-dir", type=str, default="./rl_models")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--resume", action="store_true",
                        help="从上次保存的模型继续训练")
    args = parser.parse_args()

    os.makedirs(args.save_dir, exist_ok=True)

    # 确保 rl_logs 目录存在（dashboard 从这里读取 evaluations.npz）
    rl_logs_dir = os.path.join(os.path.dirname(__file__), "rl_logs")
    os.makedirs(rl_logs_dir, exist_ok=True)

    # 日志配置：控制台输出 INFO，文件只记录 ERROR
    log_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(log_fmt)
    file_handler = logging.FileHandler(
        os.path.join(rl_logs_dir, "train_error.log"), encoding="utf-8"
    )
    file_handler.setLevel(logging.ERROR)
    file_handler.setFormatter(log_fmt)
    logger.setLevel(logging.INFO)
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

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

    logger.info("=" * 60)
    logger.info(f"SAC 训练 - 生育阶段: {args.stage} (简写: {stage_short})")
    logger.info(f"总步数: {args.timesteps}")
    logger.info("=" * 60)

    # ---- 创建环境（SAC 不需要 VecNormalize） ----
    train_env = make_env(stage_short, obs_noise=0.01)()
    eval_env = make_env(stage_short, obs_noise=0.0)()

    # ---- SAC 模型（新建 或 从 checkpoint 恢复） ----
    final_path = os.path.join(args.save_dir, f"sac_{model_tag}_final")
    if args.resume and (os.path.exists(final_path + ".zip") or
                        any(f.startswith(f"sac_{model_tag}_") for f in os.listdir(args.save_dir))):
        # 优先加载 final，否则找最新的 checkpoint
        if os.path.exists(final_path + ".zip"):
            load_path = final_path
        else:
            ckpts = sorted(
                [f for f in os.listdir(args.save_dir)
                 if f.startswith(f"sac_{model_tag}_") and f.endswith(".zip")],
                key=lambda x: int(x.split("_")[-1].replace(".zip", "").replace("steps", "")),
            )
            load_path = os.path.join(args.save_dir, ckpts[-1].replace(".zip", ""))
        model = SAC.load(load_path, env=train_env)
        trained_steps = model.num_timesteps
        logger.info(f"从 {load_path}.zip 恢复训练 (已训练 {trained_steps} 步)")
    else:
        ent_coef = sac_cfg["ent_coef"]
        if ent_coef != "auto":
            ent_coef = float(ent_coef)
        model = SAC(
            "MlpPolicy",
            train_env,
            learning_rate=float(sac_cfg["learning_rate"]),
            buffer_size=int(sac_cfg["buffer_size"]),
            batch_size=int(sac_cfg["batch_size"]),
            learning_starts=int(sac_cfg["learning_starts"]),
            tau=float(sac_cfg["tau"]),
            gamma=float(sac_cfg["gamma"]),
            ent_coef=ent_coef,
            verbose=1,
            seed=args.seed,
        )
        trained_steps = 0
        if args.resume:
            logger.warning("未找到已有模型，将从头训练")

    # ---- 回调 ----
    save_freq = max(5000, args.timesteps // int(sac_cfg["save_freq_div"]))
    eval_freq = int(sac_cfg["eval_freq"])
    n_eval_episodes = int(sac_cfg["n_eval_episodes"])
    log_interval = int(sac_cfg["log_interval"])

    keyboard_cb = KeyboardStopCallback()
    checkpoint_cb = CheckpointCallback(
        save_freq=save_freq,
        save_path=args.save_dir,
        name_prefix=f"sac_{model_tag}",
    )
    # 用 Monitor 包裹评估环境（避免 EvalCallback 警告）
    eval_env_mon = Monitor(eval_env)
    eval_cb = EvalCallback(
        eval_env_mon,
        best_model_save_path=args.save_dir,
        log_path=rl_logs_dir,
        eval_freq=eval_freq,
        deterministic=True,
        n_eval_episodes=n_eval_episodes,
    )

    # ---- 训练 ----
    logger.info(f"开始训练... (目标: +{args.timesteps} 步, 已训练: {trained_steps}, 按 q 键优雅停止)")
    try:
        model.learn(
            log_interval=log_interval,
            total_timesteps=args.timesteps,
            reset_num_timesteps=(trained_steps == 0),
            callback=[keyboard_cb, checkpoint_cb, eval_cb],
        )
    except KeyboardInterrupt:
        logger.info("用户按下 Ctrl+C，正在保存当前模型...")

    # ---- 保存最终模型（正常结束或中断都会执行） ----
    model.save(final_path)
    logger.info(f"SAC 模型已保存: {final_path}.zip (总步数: {model.num_timesteps})")
