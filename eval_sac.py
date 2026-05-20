"""
SAC 闭环评估脚本 — eval_sac.py
================================
加载训练好的 SAC 模型，在全生育期（8 次灌溉事件）上做确定性推演，
录制全部状态和控制数据，生成对比图。
"""

import argparse
import io
import os
import sys
import numpy as np

# Windows GBK 修复
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# 中文字体
try:
    simhei_path = r"C:\Windows\Fonts\simhei.ttf"
    if os.path.exists(simhei_path):
        fm.fontManager.addfont(simhei_path)
        plt.rcParams['font.sans-serif'] = ['SimHei'] + plt.rcParams.get('font.sans-serif', [])
    plt.rcParams['axes.unicode_minus'] = False
except Exception:
    pass

from digital_twin_env import DigitalTwinEnv, GrowthStage
from irrigation_schedule import get_irrigation_schedule, event_duration_hours, run_season_simulation
from config_loader import load_config

# 观测归一化边界（对齐 digital_twin_gym_env.py）
cfg_obs = load_config().obs()
OBS_LOW = np.array(cfg_obs["obs_low"], dtype=np.float32)
OBS_HIGH = np.array(cfg_obs["obs_high"], dtype=np.float32)

try:
    from stable_baselines3 import SAC
except ImportError:
    print("请安装 stable-baselines3: pip install stable-baselines3")
    sys.exit(1)

# 阶段 → 简写
STAGE_TO_TAG = {
    GrowthStage.EMERGENCE: "ini",
    GrowthStage.TUBER_INIT: "dev",
    GrowthStage.BULKING: "mid",
    GrowthStage.STARCH_ACCUMULATION: "late",
}

TAG_TO_STAGE = {v: k for k, v in STAGE_TO_TAG.items()}


def normalize_obs(obs: np.ndarray) -> np.ndarray:
    """与 DigitalTwinGymEnv 完全一致的归一化。"""
    eps = 1e-6
    norm = 2.0 * (obs - OBS_LOW) / (OBS_HIGH - OBS_LOW + eps) - 1.0
    return np.clip(norm, -1.0, 1.0).astype(np.float32)


class SACSeasonRunner:
    """加载 SAC 模型，在完整生育期上闭环运行。

    参数
    ----------
    model_dir : str
        模型目录，如 ./rl_models
    stage_models : dict or None
        指定每个阶段的模型后缀，如 {"ini": "sac_ini_final", ...}
        None 则自动查找
    single_model : str or None
        单一模型用于所有阶段（优先于 stage_models）
    """

    def __init__(self, model_dir="./rl_models", stage_models=None, single_model=None):
        self.model_dir = model_dir
        self.models = {}
        self._single = single_model

        if single_model:
            for tag in ["ini", "dev", "mid", "late"]:
                self.models[tag] = single_model
        elif stage_models:
            self.models = stage_models
        else:
            # 自动查找：sac_{tag}_final.zip
            event_tags = ["ini", "ini", "dev", "dev", "mid", "mid", "mid", "late"]
            for tag in set(event_tags):
                for key, gt in TAG_TO_STAGE.items():
                    # 尝试简写 → 完整阶段名
                    pass
            self._auto_discover()

    def _auto_discover(self):
        """自动查找各阶段的 final 模型。"""
        for tag in ["ini", "dev", "mid", "late"]:
            path = os.path.join(self.model_dir, f"sac_{tag}_final")
            if os.path.exists(path + ".zip"):
                self.models[tag] = path
        if not self.models:
            # 找不到四阶段模型，尝试单模型
            for tag in ["mid", "ini", "dev", "late"]:
                path = os.path.join(self.model_dir, f"sac_{tag}_final")
                if os.path.exists(path + ".zip"):
                    self.models = {t: path for t in ["ini", "dev", "mid", "late"]}
                    print(f"[INFO] 未找到全部阶段模型，使用单一模型: {path}")
                    break

    def _load_model(self, model_path: str, env):
        if not os.path.exists(model_path + ".zip"):
            return None
        return SAC.load(model_path, env=env)

    def get_action(self, obs: np.ndarray, stage_tag: str) -> np.ndarray:
        """给定原始观测和阶段标签，返回确定性的 SAC 动作。"""
        if stage_tag not in self.models or self.models[stage_tag] is None:
            return np.array([5.0, 1.0], dtype=np.float32)  # 回退固定策略

        path = self.models[stage_tag]
        # 缓存加载
        if not hasattr(self, "_loaded_models"):
            self._loaded_models = {}

        if stage_tag not in self._loaded_models:
            self._loaded_models[stage_tag] = SAC.load(path)
            print(f"  [加载] {path}.zip")

        model = self._loaded_models[stage_tag]
        norm_obs = normalize_obs(obs)
        action, _ = model.predict(norm_obs, deterministic=True)
        return action.astype(np.float32)


def run_eval(args):
    """主评估流程。"""
    cfg = load_config()
    irr_cfg = cfg.irrigation()

    print("=" * 60)
    print("SAC 闭环评估 — 全生育期推演")
    print("=" * 60)

    # ---- 1. 初始化模型加载器 ----
    runner = SACSeasonRunner(
        model_dir=args.model_dir,
        single_model=args.model if args.model else None,
    )

    if not runner.models:
        print("[ERROR] 未找到任何 SAC 模型，请先训练。")
        print(f"  检查目录: {os.path.abspath(args.model_dir)}")
        sys.exit(1)

    print(f"阶段模型配置: {runner.models}")
    print()

    # ---- 2. 创建环境（DigitalTwinEnv，需要用 Gym 的归一化） ----
    schedule = get_irrigation_schedule()
    env = DigitalTwinEnv(
        growth_stage=schedule[0].growth_stage,
        area_ha=args.area_ha,
        dt_min=args.dt_min,
        ep_len_days=90.0,
        et0_mm_day=args.et0,
        seed=args.seed,
    )

    # ---- 3. 录制数据结构 ----
    history = {
        "time_day": [], "theta": [], "ec_soil": [], "target_ec": [],
        "q_f": [], "q_a": [], "irrigation_mm_h": [], "etc_mm_h": [],
        "ec_drip": [], "ph_drip": [],
        "stage_tag": [], "event_idx": [],
    }

    obs = env.reset()
    env.soil.theta = irr_cfg.get("initial_theta") or env.soil.theta_fc
    env.soil.ec_soil = irr_cfg.get("initial_ec", 0.1)
    env._theta_history.clear()
    env._ec_soil_history.clear()
    for _ in range(env.history_len):
        env._theta_history.append(env.soil.theta)
        env._ec_soil_history.append(env.soil.ec_soil)

    total_irr_mm = 0.0
    total_etc_mm = 0.0
    prev_day = 0.0
    dt_hours = args.dt_min / 60.0
    rain_mm_h = irr_cfg.get("rain_mm_day", 2.0) / 24.0

    event_tags = ["ini", "ini", "dev", "dev", "mid", "mid", "mid", "late"]

    print("按灌溉事件推进...")
    print("-" * 60)

    for i, (event, tag) in enumerate(zip(schedule, event_tags)):
        env.set_growth_stage(event.growth_stage)
        stage_name = event.growth_stage.value

        # ---- 干旱期（蒸发 + 降雨） ----
        dry_hours = (event.day - prev_day) * 24.0
        dry_steps = int(dry_hours / dt_hours)
        for _ in range(dry_steps):
            obs, _, done, info = env.dry_step(rain_mm_h=rain_mm_h)
            total_etc_mm += info["etc_mm_h"] * dt_hours
            _append(history, info, np.array([0.0, 0.0]), tag, i)

        # ---- 灌溉期（SAC 控制） ----
        amount = event.t2_amount_m3ha  # 用 T2 水量确定时长
        event_hours = event_duration_hours(amount, args.area_ha)
        event_steps = max(1, int(event_hours / dt_hours))
        event_irr = 0.0

        for step in range(event_steps):
            action = runner.get_action(obs, tag)
            obs, reward, done, info = env.step(action)
            total_irr_mm += info["irrigation_mm_h"] * dt_hours
            event_irr += info["irrigation_mm_h"] * dt_hours
            total_etc_mm += info["etc_mm_h"] * dt_hours
            _append(history, info, action, tag, i)

        target_ec = env.crop.get_target_ec(event.growth_stage)
        theta = info.get("theta", 0)
        ec = info.get("ec_soil", 0)
        print(f"  事件 {i+1}/8  day {event.day:3.0f}  "
              f"stage={stage_name:20s}  tag={tag}  "
              f"irr={event_irr:.1f}mm  theta={theta:.3f}  EC={ec:.3f}  target={target_ec:.2f}")

        prev_day = event.day

    # ---- 4. 统计摘要 ----
    print()
    print("=" * 60)
    print("评估汇总")
    print("=" * 60)
    theta_arr = np.array(history["theta"])
    ec_arr = np.array(history["ec_soil"])
    target_arr = np.array(history["target_ec"])
    qf_arr = np.array(history["q_f"])
    qa_arr = np.array(history["q_a"])

    ec_mae = np.abs(ec_arr - target_arr).mean()
    print(f"  总步数:          {len(history['time_day'])}")
    print(f"  总灌溉量:        {total_irr_mm:.1f} mm")
    print(f"  总蒸散发:        {total_etc_mm:.1f} mm")
    print(f"  平均 theta:      {theta_arr.mean():.4f} ± {theta_arr.std():.4f}")
    print(f"  EC 跟踪 MAE:     {ec_mae:.4f} dS/m")
    print(f"  q_f 均值/范围:   {qf_arr.mean():.2f} / [{qf_arr.min():.2f}, {qf_arr.max():.2f}]")
    print(f"  q_a 均值/范围:   {qa_arr.mean():.2f} / [{qa_arr.min():.2f}, {qa_arr.max():.2f}]")

    # WUE 代理
    wue = total_etc_mm / (total_irr_mm + irr_cfg.get("rain_mm_day", 2.0) * 65 + 1e-6)
    print(f"  WUE 代理:        {wue:.4f}")

    # ---- 5. 对比 T1/T2 基线 ----
    print()
    print("--- 对比基线 (T1/T2) ---")
    for strategy in ["T1", "T2"]:
        env2 = DigitalTwinEnv(
            growth_stage=schedule[0].growth_stage,
            area_ha=args.area_ha,
            dt_min=args.dt_min,
            ep_len_days=90.0,
            et0_mm_day=args.et0,
            seed=args.seed,
        )
        res = run_season_simulation(
            env2, strategy=strategy, area_ha=args.area_ha,
            dt_min=args.dt_min, rain_mm_day=irr_cfg.get("rain_mm_day"),
            initial_theta=env2.soil.theta_fc, initial_ec=0.1, verbose=False,
        )
        ec_m = np.abs(res["ec_soil"] - res["target_ec"]).mean()
        w = res["total_etc_mm"] / (res["total_irrigation_mm"] + irr_cfg.get("rain_mm_day", 2.0) * 65 + 1e-6)
        print(f"  {strategy}: 灌溉={res['total_irrigation_mm']:.1f}mm  "
              f"EC_MAE={ec_m:.4f}  WUE={w:.4f}  theta_CV={res['theta'].std()/res['theta'].mean():.4f}")

    # ---- 6. 绘图 ----
    time_day = np.array(history["time_day"])
    fig, axes = plt.subplots(4, 1, figsize=(14, 14), sharex=True)

    # theta
    axes[0].plot(time_day, theta_arr, 'b-', linewidth=1.0, alpha=0.8)
    axes[0].axhline(y=0.32, color='gray', linestyle='--', alpha=0.5, label='FC')
    axes[0].axhline(y=0.04, color='r', linestyle=':', alpha=0.5, label='WP')
    axes[0].set_ylabel('theta (m³/m³)')
    axes[0].set_title('根区含水率 — SAC 闭环控制')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    # EC
    axes[1].plot(time_day, ec_arr, 'r-', linewidth=1.0, alpha=0.8, label='EC_soil')
    axes[1].plot(time_day, target_arr, 'g--', linewidth=1.5, label='Target EC')
    axes[1].set_ylabel('EC (dS/m)')
    axes[1].set_title('根区 EC 跟踪')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    # 动作
    axes[2].plot(time_day, qf_arr, 'g-', linewidth=0.8, alpha=0.7, label='q_f (母液)')
    axes[2].plot(time_day, qa_arr, 'm-', linewidth=0.8, alpha=0.7, label='q_a (酸液)')
    axes[2].set_ylabel('Flow (L/min)')
    axes[2].set_title('SAC 动作序列')
    axes[2].legend()
    axes[2].grid(True, alpha=0.3)

    # 灌溉 + ET
    irr_arr = np.array(history["irrigation_mm_h"])
    etc_arr = np.array(history["etc_mm_h"])
    axes[3].fill_between(time_day, 0, irr_arr, color='b', alpha=0.3, label='Irrigation')
    axes[3].plot(time_day, etc_arr, 'orange', linewidth=1.0, label='ET (mm/h)')
    axes[3].set_xlabel('出苗后天数')
    axes[3].set_ylabel('Rate (mm/h)')
    axes[3].set_title('灌溉与蒸散发')
    axes[3].legend()
    axes[3].grid(True, alpha=0.3)

    plt.tight_layout()

    out_dir = os.path.join(os.path.dirname(__file__), "pic_output", "eval_sac")
    os.makedirs(out_dir, exist_ok=True)
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = os.path.join(out_dir, f"sac_eval_{ts}.png")
    plt.savefig(fname, dpi=150)
    print(f"\n图表已保存: {fname}")
    plt.close()


def _append(hist, info, action, tag, idx):
    hist["time_day"].append(info["time_day"])
    hist["theta"].append(info["theta"])
    hist["ec_soil"].append(info["ec_soil"])
    hist["target_ec"].append(info["target_ec"])
    hist["q_f"].append(action[0])
    hist["q_a"].append(action[1])
    hist["irrigation_mm_h"].append(info["irrigation_mm_h"])
    hist["etc_mm_h"].append(info["etc_mm_h"])
    hist["ec_drip"].append(info.get("ec_drip", 0))
    hist["ph_drip"].append(info.get("ph_drip", 7.0))
    hist["stage_tag"].append(tag)
    hist["event_idx"].append(idx)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SAC 闭环评估")
    parser.add_argument("--model-dir", default="./rl_models")
    parser.add_argument("--model", default=None,
                        help="单一模型路径（不含 .zip）；缺省则自动查找四阶段模型")
    parser.add_argument("--area-ha", type=float, default=0.1)
    parser.add_argument("--dt-min", type=float, default=15.0)
    parser.add_argument("--et0", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    run_eval(args)
