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
import json
import hashlib
from datetime import datetime, timezone
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

def make_env(stage_name: str, obs_noise: float = None, reward_scale: float = None,
             soil_model: str = None, domain_randomization: bool = False):
    """创建环境的工厂函数（环境参数从 simulation.yaml 读取）。"""
    env_cfg = load_config().env()
    sac_cfg = load_config().sac()
    def _init():
        env = DigitalTwinGymEnv(
            growth_stage=stage_name,
            area_ha=env_cfg["area_ha"],
            dt_min=env_cfg["dt_min"],
            ep_len_days=env_cfg["ep_len_days"],
            et0_mm_day=env_cfg["et0_mm_day"],
            obs_noise_std=obs_noise if obs_noise is not None else env_cfg["obs_noise_std"],
            reward_scale=reward_scale if reward_scale is not None else sac_cfg.get("reward_scale", 0.1),
            soil_model=soil_model,
            domain_randomization=domain_randomization,
            stage_aware=(stage_name.upper() == "ALL"),
        )
        return env
    return _init


def _configuration_fingerprint(soil_model: str) -> tuple[str, dict]:
    cfg = load_config()
    payload = {
        "soil_model": soil_model,
        "soil_v2": cfg.soil_v2() if soil_model == "layered_v2" else cfg.soil(),
        "mixing_tank": cfg.mixing_tank(),
        "pipe": cfg.pipe(),
        "action": cfg.action(),
        "calibration": cfg.calibration(),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16], payload


def _check_model_metadata(model_path: str, fingerprint: str, allow_mismatch: bool) -> None:
    metadata_path = model_path + ".metadata.json"
    if not os.path.exists(metadata_path):
        message = f"Model metadata is missing; legacy action semantics cannot be excluded: {model_path}"
        if allow_mismatch:
            logger.warning(message)
            return
        raise RuntimeError(message)
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    previous = metadata.get("configuration_fingerprint")
    if previous and previous != fingerprint:
        message = (f"Model configuration {previous} differs from current {fingerprint}. "
                   "Use --fresh, or explicitly pass --allow-config-mismatch.")
        if allow_mismatch:
            logger.warning(message)
        else:
            raise RuntimeError(message)


if __name__ == "__main__":
    sac_cfg = load_config().sac()

    parser = argparse.ArgumentParser(description="SAC 训练")
    parser.add_argument("--timesteps", type=int, default=sac_cfg["total_timesteps"],
                        help="总训练步数")
    parser.add_argument("--stage", type=str, default="ALL",
                         choices=["ALL", "INI", "DEV", "MID", "LATE"],
                         help="ALL trains the single stage-aware V2 policy")
    parser.add_argument("--save-dir", type=str, default="./rl_models")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--resume", action="store_true",
                        help="从上次保存的模型继续训练")
    parser.add_argument("--fresh", action="store_true",
                        help="忽略已有模型并从头训练，适合配置变化后的可重复实验")
    parser.add_argument("--load-path", type=str, default=None,
                        help="从指定模型路径加载 (如 sac_mid_6000_steps)")
    parser.add_argument(
        "--soil-model",
        choices=["lumped_v1", "layered_v2"],
        default=load_config().soil_v2().get("default_model", "lumped_v1"),
        help="土壤数字孪生后端；layered_v2 用于新版分层模型训练",
    )
    parser.add_argument(
        "--disable-domain-randomization", action="store_true",
        help="Disable layered-soil domain randomization for an ablation run.",
    )
    parser.add_argument(
        "--allow-config-mismatch", action="store_true",
        help="Allow loading a model trained with a different configuration fingerprint.",
    )
    args = parser.parse_args()

    if args.resume and args.fresh:
        parser.error("--resume 和 --fresh 不能同时使用")
    if args.load_path and args.fresh:
        parser.error("--load-path 和 --fresh 不能同时使用")

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

    # 阶段名简写
    stage_short = args.stage.upper()
    model_tag = "residual_all" if stage_short == "ALL" else f"residual_{stage_short.lower()}"
    stage_eval_log_dir = os.path.join(rl_logs_dir, model_tag)
    stage_best_model_dir = os.path.join(args.save_dir, f"best_{model_tag}")
    os.makedirs(stage_eval_log_dir, exist_ok=True)
    os.makedirs(stage_best_model_dir, exist_ok=True)

    logger.info("=" * 60)
    logger.info(f"SAC 训练 - 生育阶段: {args.stage} (简写: {stage_short})")
    logger.info(f"总步数: {args.timesteps}")
    logger.info(f"土壤模型: {args.soil_model}")
    logger.info("=" * 60)

    # ---- 创建环境（SAC 不需要 VecNormalize） ----
    config_fingerprint, config_payload = _configuration_fingerprint(args.soil_model)
    calibration = load_config().calibration()
    logger.info(f"Configuration fingerprint: {config_fingerprint}")
    if calibration:
        logger.info(f"Active calibration: {calibration.get('id', calibration.get('active_profile', 'unknown'))}")

    use_randomization = (
        args.soil_model == "layered_v2" and not args.disable_domain_randomization
    )
    train_env = make_env(
        stage_short, soil_model=args.soil_model,
        domain_randomization=use_randomization,
    )()
    eval_env = make_env(
        stage_short, obs_noise=0.0, soil_model=args.soil_model,
        domain_randomization=False,
    )()

    # ---- SAC 模型（新建 或 从 checkpoint 恢复） ----
    final_path = os.path.join(args.save_dir, f"sac_{model_tag}_final")
    model_found = (os.path.exists(final_path + ".zip") or
                   any(f.startswith(f"sac_{model_tag}_") for f in os.listdir(args.save_dir)))

    # 如果指定了 --load-path，直接加载该模型
    trained_steps = 0
    if args.load_path:
        load_path = os.path.join(args.save_dir, args.load_path)
        if not os.path.exists(load_path + ".zip"):
            logger.error(f"指定模型不存在: {load_path}.zip")
            sys.exit(1)
        _check_model_metadata(load_path, config_fingerprint, args.allow_config_mismatch)
        model = SAC.load(load_path)
        model.observation_space = train_env.observation_space
        model.set_env(train_env)
        trained_steps = model.num_timesteps
        logger.info(f"从指定模型 {args.load_path}.zip 继续训练 (已训练 {trained_steps} 步)")
    else:
        # 检测上次训练是否已完成
        already_completed = False
        if model_found:
            try:
                tmp = SAC.load(final_path if os.path.exists(final_path + ".zip") else
                              os.path.join(args.save_dir,
                                           sorted([f for f in os.listdir(args.save_dir)
                                                   if f.startswith(f"sac_{model_tag}_") and f.endswith(".zip") and "_final" not in f],
                                                  key=lambda x: int(x.split("_")[-2]))[-1].replace(".zip", "")))
                if tmp.num_timesteps >= args.timesteps:
                    already_completed = True
                    logger.info(f"检测到上次训练已完成 ({tmp.num_timesteps} >= {args.timesteps})，将从头开始新训练")
                del tmp
            except Exception:
                pass

        if args.fresh:
            ent_coef = sac_cfg["ent_coef"]
            if ent_coef != "auto":
                ent_coef = float(ent_coef)
            model = SAC(
                "MlpPolicy", train_env,
                learning_rate=float(sac_cfg["learning_rate"]),
                buffer_size=int(sac_cfg["buffer_size"]),
                batch_size=int(sac_cfg["batch_size"]),
                learning_starts=int(sac_cfg["learning_starts"]),
                tau=float(sac_cfg["tau"]),
                gamma=float(sac_cfg["gamma"]),
                ent_coef=ent_coef, verbose=1, seed=args.seed,
            )
            trained_steps = 0
            logger.info("已指定 --fresh，将忽略已有模型并从头训练")
        elif model_found and not already_completed:
            if args.resume:
                should_resume = True
            else:
                # 交互式询问（无终端时默认不续训）
                try:
                    ans = input(f"\n检测到已有模型，是否从上次模型继续训练? [y/N]: ").strip().lower()
                    should_resume = (ans == "y" or ans == "yes")
                except (EOFError, KeyboardInterrupt, OSError):
                    should_resume = False
                    logger.info("无交互终端，默认从头训练")

            if should_resume:
                # 优先加载 final，否则找最新的 checkpoint
                if os.path.exists(final_path + ".zip"):
                    load_path = final_path
                else:
                    ckpts = sorted(
                        [f for f in os.listdir(args.save_dir)
                         if f.startswith(f"sac_{model_tag}_") and f.endswith(".zip") and "_final" not in f],
                        key=lambda x: int(x.split("_")[-2]),
                    )
                    load_path = os.path.join(args.save_dir, ckpts[-1].replace(".zip", ""))
                _check_model_metadata(load_path, config_fingerprint, args.allow_config_mismatch)
                model = SAC.load(load_path)
                model.observation_space = train_env.observation_space
                model.set_env(train_env)
                trained_steps = model.num_timesteps
                logger.info(f"从 {load_path}.zip 恢复训练 (已训练 {trained_steps} 步)")
            else:
                ent_coef = sac_cfg["ent_coef"]
                if ent_coef != "auto":
                    ent_coef = float(ent_coef)
                model = SAC(
                    "MlpPolicy", train_env,
                    learning_rate=float(sac_cfg["learning_rate"]),
                    buffer_size=int(sac_cfg["buffer_size"]),
                    batch_size=int(sac_cfg["batch_size"]),
                    learning_starts=int(sac_cfg["learning_starts"]),
                    tau=float(sac_cfg["tau"]),
                    gamma=float(sac_cfg["gamma"]),
                    ent_coef=ent_coef, verbose=1, seed=args.seed,
                )
                trained_steps = 0
                logger.info("用户选择从头训练")
        else:
            ent_coef = sac_cfg["ent_coef"]
            if ent_coef != "auto":
                ent_coef = float(ent_coef)
            model = SAC(
                "MlpPolicy", train_env,
                learning_rate=float(sac_cfg["learning_rate"]),
                buffer_size=int(sac_cfg["buffer_size"]),
                batch_size=int(sac_cfg["batch_size"]),
                learning_starts=int(sac_cfg["learning_starts"]),
                tau=float(sac_cfg["tau"]),
                gamma=float(sac_cfg["gamma"]),
                ent_coef=ent_coef, verbose=1, seed=args.seed,
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
        best_model_save_path=stage_best_model_dir,
        log_path=stage_eval_log_dir,
        eval_freq=eval_freq,
        deterministic=True,
        n_eval_episodes=n_eval_episodes,
    )

    # ---- 训练 ----
    # SB3: 当 reset_num_timesteps=False 时会累加 num_timesteps 到 total_timesteps，
    # 因此 resume 时必须传入剩余步数（非总步数），否则最终总步数会超标
    remaining_steps = max(0, args.timesteps - trained_steps)
    logger.info(f"开始训练... (目标总步数: {args.timesteps}, 已训练: {trained_steps}, "
                f"本次新增: {remaining_steps}, 按 q 键优雅停止)")
    try:
        model.learn(
            log_interval=log_interval,
            total_timesteps=remaining_steps,
            reset_num_timesteps=(trained_steps == 0),
            callback=[keyboard_cb, checkpoint_cb, eval_cb],
        )
    except KeyboardInterrupt:
        logger.info("用户按下 Ctrl+C，正在保存当前模型...")

    # ---- 保存最终模型（正常结束或中断都会执行） ----
    model.save(final_path)
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stage": stage_short,
        "soil_model": args.soil_model,
        "configuration_fingerprint": config_fingerprint,
        "calibration": load_config().calibration(),
        "domain_randomization": use_randomization,
        "num_timesteps": int(model.num_timesteps),
        "configuration": config_payload,
    }
    with open(final_path + ".metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    logger.info(f"SAC model saved: {final_path}.zip (timesteps: {model.num_timesteps})")
    logger.info(f"Configuration metadata saved: {final_path}.metadata.json")
