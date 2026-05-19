"""
PPO 策略评估 — eval_ppo.py
============================
加载训练的模型，跑多个 episode（不同生育阶段），
绘制 EC 跟踪曲线，计算 MAE。

用法：
    python eval_ppo.py
    python eval_ppo.py --model ./rl_models/ppo_mid_final
    python eval_ppo.py --stages INI DEV MID LATE
"""

import argparse
import os
import random
import numpy as np
from datetime import datetime

from digital_twin_gym_env import DigitalTwinGymEnv, STAGE_NAMES

try:
    from stable_baselines3 import PPO
    SB3_AVAILABLE = True
except ImportError:
    SB3_AVAILABLE = False

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm

    # 注册 Windows 系统黑体字体以支持中文
    simhei_path = r"C:\Windows\Fonts\simhei.ttf"
    if __import__("os").path.exists(simhei_path):
        fm.fontManager.addfont(simhei_path)
        plt.rcParams["font.sans-serif"] = ["SimHei"] + plt.rcParams["font.sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False

    PLT_AVAILABLE = True
except ImportError:
    PLT_AVAILABLE = False


def evaluate(model_path: str, stages=None, n_episodes: int = 3, save_fig: bool = True):
    """评估模型，绘制 EC 跟踪图。

    参数
    ----------
    model_path : str
        模型路径（不含 .zip）
    stages : list[str], optional
        要评估的阶段列表（简写: INI/DEV/MID/LATE）；
        若为 None 则随机选 n_episodes 个
    n_episodes : int
        episode 数（仅 stages=None 时生效）
    save_fig : bool
        是否保存图片
    """
    if stages is None:
        stages = random.sample(STAGE_NAMES, min(n_episodes, len(STAGE_NAMES)))

    if SB3_AVAILABLE and os.path.exists(model_path + ".zip"):
        model = PPO.load(model_path)
        print(f"[PPO] 模型加载: {model_path}")
        use_ppo = True
    else:
        print(f"[WARN] 模型不存在: {model_path}.zip，使用固定策略 (q_f=1.2, q_a=0.3)")
        model = None
        use_ppo = False

    results = []

    for stage_name in stages:
        print(f"\n{'='*50}")
        print(f"评估阶段: {stage_name}")
        print(f"{'='*50}")

        env = DigitalTwinGymEnv(
            growth_stage=stage_name,
            area_ha=0.1,
            dt_min=60.0,
            ep_len_days=5.0,
            et0_mm_day=5.0,
            obs_noise_std=0.0,
            reward_scale=1.0,
        )

        obs, _ = env.reset()
        history = {
            "time_day": [], "theta": [], "ec_soil": [],
            "target_ec": [], "reward": [], "q_f": [], "q_a": [],
        }

        done = False
        while not done:
            if use_ppo:
                action, _ = model.predict(obs, deterministic=True)
            else:
                action = np.array([5.0, 1.0], dtype=np.float32)

            obs, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated

            # 从底层 DigitalTwinEnv 获取真实（非归一化）值
            raw_env = env.unwrapped_env
            history["time_day"].append(info["time_day"])
            history["theta"].append(info["theta"])
            history["ec_soil"].append(info["ec_soil"])
            history["target_ec"].append(info["target_ec"])
            history["reward"].append(reward)
            history["q_f"].append(info["q_f"])
            history["q_a"].append(info["q_a"])

        ec_arr = np.array(history["ec_soil"])
        target_arr = np.array(history["target_ec"])
        mae = float(np.mean(np.abs(ec_arr - target_arr)))
        results.append((stage_name, mae, history))

        print(f"  步数: {len(history['time_day'])}")
        print(f"  EC MAE: {mae:.4f} dS/m")
        print(f"  总奖励: {sum(history['reward']):.2f}")

    # ---- 绘图 ----
    if PLT_AVAILABLE and save_fig:
        n_plots = len(results)
        fig, axes = plt.subplots(n_plots, 1, figsize=(12, 4 * n_plots), squeeze=False)

        for idx, (stage_name, mae, hist) in enumerate(results):
            ax = axes[idx, 0]

            ax.plot(hist["time_day"], hist["ec_soil"], "b-", linewidth=2, label="EC_soil")
            ax.plot(hist["time_day"], hist["target_ec"], "r--", linewidth=2, label="Target EC")
            ax.fill_between(
                hist["time_day"],
                np.array(hist["target_ec"]) - 0.2,
                np.array(hist["target_ec"]) + 0.2,
                alpha=0.15, color="red", label="±0.2 dS/m"
            )
            ax.set_ylabel("EC (dS/m)")
            ax.set_title(f"{stage_name} — EC 跟踪 (MAE={mae:.4f})")
            ax.legend()
            ax.grid(True, alpha=0.3)

            # 第二个 y 轴显示动作
            ax2 = ax.twinx()
            ax2.plot(hist["time_day"], hist["q_f"], "g-", alpha=0.5, linewidth=1, label="q_f")
            ax2.set_ylabel("流量 (L/min)", color="green")
            ax2.tick_params(axis="y", labelcolor="green")

        axes[-1, 0].set_xlabel("时间 (天)")
        plt.tight_layout()
        out_dir = os.path.join(os.path.dirname(__file__), "pic_output", "ppo_eval")
        os.makedirs(out_dir, exist_ok=True)
        fig_path = os.path.join(out_dir, f"{datetime.now().strftime('%Y%m%d%H%M%S')}.png")
        plt.savefig(fig_path, dpi=150)
        print(f"\n[OK] 图片已保存: {fig_path}")
        plt.close()

    # ---- 汇总 ----
    print("\n" + "=" * 50)
    print("评估汇总")
    print("=" * 50)
    for stage_name, mae, _ in results:
        print(f"  {stage_name:8s}  MAE = {mae:.4f} dS/m")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PPO 策略评估")
    parser.add_argument("--model", type=str, default="./rl_models/ppo_mid_final")
    parser.add_argument("--stages", type=str, nargs="+",
                        choices=STAGE_NAMES,
                        default=None)
    parser.add_argument("--n-episodes", type=int, default=3)
    args = parser.parse_args()

    evaluate(args.model, stages=args.stages, n_episodes=args.n_episodes)
