"""
HIL 推理部署脚本 — run_hil.py
===============================
加载训练好的 SAC 模型，连接 PLC，在单个灌溉事件上做硬件在环推理。
适合验证 PLC 通讯、看门狗、斜坡护盾等真实工况。

用法:
    python run_hil.py --stage MID
    python run_hil.py --stage MID --steps 100 --model ./rl_models/sac_mid_final
"""

import argparse
import logging
import os
import sys
import time
import numpy as np

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HIL 推理部署")
    parser.add_argument("--stage", default="MID",
                        choices=["INI", "DEV", "MID", "LATE"])
    parser.add_argument("--steps", type=int, default=60,
                        help="推理步数 (60 步 ≈ 1 小时灌溉)")
    parser.add_argument("--model", default=None,
                        help="模型路径（不含 .zip），默认自动查找")
    parser.add_argument("--area-ha", type=float, default=0.1)
    parser.add_argument("--et0", type=float, default=5.0)
    parser.add_argument("--manual-test", action="store_true",
                        help="不加载 SAC，直接用固定 EC/pH 目标测试 PLC 执行层")
    parser.add_argument("--ec-set", type=float, default=1.5,
                        help="--manual-test 时写入 PLC 的目标 EC")
    parser.add_argument("--ph-set", type=float, default=6.0,
                        help="--manual-test 时写入 PLC 的目标 pH")
    args = parser.parse_args()

    try:
        from plc_client import PLCClient
        from plc_gym_env import PLCGymEnv
    except ModuleNotFoundError as exc:
        if exc.name == "snap7":
            logger.error("缺少 python-snap7，请先安装: pip install python-snap7")
            sys.exit(10)
        raise

    # ---- 1. 查找模型 ----
    model = None
    model_path = args.model
    if not args.manual_test:
        try:
            from stable_baselines3 import SAC
        except ImportError:
            logger.error("请安装 stable-baselines3: pip install stable-baselines3")
            sys.exit(1)

        if model_path is None:
            model_path = f"./rl_models/sac_{args.stage.lower()}_final"
        if not os.path.exists(model_path + ".zip"):
            logger.error(f"模型不存在: {model_path}.zip")
            sys.exit(1)

    # ---- 2. 连接 PLC ----
    logger.info("正在连接 PLC...")
    plc = PLCClient()
    if not plc.connect():
        logger.error("PLC 连接失败，请检查 PLCSIM / NetToPLCsim 是否运行")
        sys.exit(1)

    # ---- 3. 创建 HIL 环境 ----
    env = PLCGymEnv(
        plc_client=plc,
        growth_stage=args.stage,
        area_ha=args.area_ha,
        dt_min=60.0,
        et0_mm_day=args.et0,
        reward_scale=1.0,
    )   

    # ---- 4. 加载 SAC 模型，或进入手动 EC/pH 目标测试 ----
    if args.manual_test:
        logger.info("手动 PLC 测试模式: EC_set=%.3f, pH_set=%.3f", args.ec_set, args.ph_set)
    else:
        logger.info(f"加载模型: {model_path}.zip")
        model = SAC.load(model_path)
        model.observation_space = env.observation_space  # 兼容旧模型
        model.set_env(env)

    # ---- 5. HIL 推理循环 ----
    obs, _ = env.reset()

    logger.info("=" * 60)
    logger.info(f"HIL 推理开始 — {args.stage} 阶段, {args.steps} 步")
    logger.info("=" * 60)

    total_reward = 0.0
    plc_ok_count = 0

    try:
        for step in range(args.steps):
            # B 方案动作含义：[EC_set, pH_set]，不是 q_f/q_a。
            if args.manual_test:
                action = np.array([args.ec_set, args.ph_set], dtype=np.float32)
            else:
                action, _ = model.predict(obs, deterministic=True)

            # HIL step: 写 PLC → 等执行 → 读 PLC → 仿真实时推进
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
    
            plc_state = info.get("plc", {})
            if plc_state.get("Remote_Comms_OK"):
                plc_ok_count += 1

            logger.info(
                f"[{step+1:3d}/{args.steps}] "
                f"EC_set={action[0]:5.2f} pH_set={action[1]:5.2f} | "
                f"PLC: q_f={plc_state.get('q_f_cmd', 0):5.3f} "
                f"q_a={plc_state.get('q_a_cmd', 0):5.3f} "
                f"CommOK={plc_state.get('Remote_Comms_OK')} "
                f"Alarm={plc_state.get('System_Alarm_Light')} | "
                f"Outlet: EC={info.get('ec_drip', 0):.3f} pH={info.get('ph_drip', 0):.3f} | "
                f"Root: θ={info.get('theta', 0):.3f} EC={info.get('ec_soil', 0):.3f}"
            )

            if terminated or truncated:
                logger.info("Episode 结束")
                break

    except KeyboardInterrupt:
        logger.info("\n用户中断")

    finally:
        # ---- 6. 安全退出 ----
        logger.info("安全切断阀门...")
        env.close()  # 自动写 0 + 断开 PLC

        logger.info("=" * 60)
        logger.info(f"推理完成 — 总步数: {step+1}, 累计奖励: {total_reward:.2f}")
        logger.info(f"PLC 通讯正常率: {plc_ok_count}/{step+1} "
                    f"({100*plc_ok_count/(step+1):.1f}%)")
        logger.info("=" * 60)
