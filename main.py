"""
马铃薯施肥灌溉数字孪生系统 — 统一启动入口
==============================================
提供菜单选择不同的运行模式：
  1. 仿真运行（固定策略）
  2. 仿真运行（SAC 动态控制）
  3. 训练 SAC 模型
  4. 查看训练进度
  5. 季节仿真 T1 vs T2 对比
"""

import argparse
import io
import logging
import os
import subprocess
import sys
from datetime import datetime
from config_loader import load_config
from sac_model_registry import get_stage_model_path
from weather_client import get_et0_rain
from plot_style import (
    apply_academic_style, style_axis, set_ylim_tight,
    EC_ACTUAL, EC_TARGET, THETA, QF, QA, ET_COLOR, IRRIGATION,
    FC_LINE, WP_LINE, T1, T2,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(message)s')
_error_fh = logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rl_logs', 'error.log'), encoding='utf-8')
_error_fh.setLevel(logging.ERROR)
_error_fh.setFormatter(logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s'))
logging.getLogger().addHandler(_error_fh)

# Windows GBK 编码修复
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

# ---- 中文字体设置 ----
try:
    simhei_path = r"C:\Windows\Fonts\simhei.ttf"
    if os.path.exists(simhei_path):
        fm.fontManager.addfont(simhei_path)
        plt.rcParams['font.sans-serif'] = ['SimHei'] + plt.rcParams.get('font.sans-serif', [])
    plt.rcParams['axes.unicode_minus'] = False
except Exception:
    pass


_OUTPUT_DIRS = {
    "1": "fixed_policy",
    "2": "sac_control",
    "5": "season_comparison",
}


def _make_output_path(mode: str, suffix: str = "") -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    sub = _OUTPUT_DIRS.get(mode, f"mode_{mode}")
    out_dir = os.path.join(os.path.dirname(__file__), "pic_output", sub)
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, f"{ts}{suffix}.png")


def _get_weather_or_default(use_weather: bool):
    """获取天气数据或回退到 config 默认值。"""
    if not use_weather:
        env_cfg = load_config().env()
        irr_cfg = load_config().irrigation()
        return env_cfg["et0_mm_day"], irr_cfg.get("rain_mm_day", 2.0), False

    try:
        et0, rain = get_et0_rain()
        logger.info(f"[天气] 察右中旗 今日 ET0={et0:.1f} mm/天, 降雨={rain:.1f} mm/天")
        return et0, rain, True
    except Exception as e:
        logger.error(f"[天气] 获取失败 ({e})，回退到 config.yaml 默认值")
        env_cfg = load_config().env()
        irr_cfg = load_config().irrigation()
        return env_cfg["et0_mm_day"], irr_cfg.get("rain_mm_day", 2.0), False


# ============================================================
#  选项 1-2：仿真运行
# ============================================================

def run_simulation(model_type: str = "none", mode: str = "1",
                   use_weather: bool = False):
    """运行仿真并绘图。

    参数
    ----------
    model_type : str
        "none" = 固定策略, "sac" = SAC
    mode : str
        模式编号 "1"~"2"
    use_weather : bool
        是否使用真实天气数据
    """
    from digital_twin_env import DigitalTwinEnv
    from digital_twin_gym_env import DigitalTwinGymEnv
    from crop_model import GrowthStage

    logger.info("=" * 60)
    logger.info("Potato Fertigation Digital Twin - Simulation")
    logger.info("=" * 60)

    et0_val, rain_val, from_weather = _get_weather_or_default(use_weather)

    use_rl = model_type == "sac"
    if use_rl:
        env = DigitalTwinGymEnv(
            growth_stage="MID",
            area_ha=0.1,
            dt_min=60.0,
            ep_len_days=5.0,
            et0_mm_day=et0_val,
        )
        obs, _ = env.reset()

        from stable_baselines3 import SAC as RLModel
        model_path = str(get_stage_model_path("mid"))

        if os.path.exists(model_path + ".zip"):
            model = RLModel.load(model_path)
            logger.info(f"[SAC] 模型加载: {model_path}")
        else:
            logger.error(f"[WARN] 模型 {model_path}.zip 不存在，回退到固定策略")
            model = None
            use_rl = False
    else:
        env = DigitalTwinEnv(
            growth_stage=GrowthStage.BULKING,
            area_ha=0.1,
            dt_min=60.0,
            ep_len_days=5.0,
            et0_mm_day=et0_val,
        )
        obs = env.reset()

    mode_labels = {"none": "固定策略 [5.0, 1.0]", "sac": "SAC 动态控制"}
    mode_label_short = {"none": "Fixed", "sac": "SAC"}
    mode_label = mode_label_short.get(model_type, model_type)
    logger.info(f"Observation dim: {len(obs)}")
    logger.info(f"Control mode: {mode_labels.get(model_type, model_type)}")

    # 数据记录
    time_hours = []
    theta_vals = []
    ec_soil_vals = []
    ec_drip_vals = []
    et_vals = []
    irrigation_vals = []
    target_ec_vals = []
    q_f_vals = []
    q_a_vals = []

    logger.info("\nRunning simulation (5 days)...")
    done = False
    step_count = 0
    while not done:
        # 选择动作
        if use_rl and model is not None:
            action, _ = model.predict(obs, deterministic=True)
        else:
            action = np.array(load_config().action()["fixed_strategy"], dtype=np.float32)

        # 兼容 Gymnasium 和旧版 API
        if hasattr(env, 'action_space'):  # Gymnasium 环境 → 5 个返回值
            obs, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated
        else:  # 旧版 DigitalTwinEnv → 4 个返回值
            obs, reward, done, info = env.step(action)

        t_hour = info['time_day'] * 24.0
        time_hours.append(t_hour)
        theta_vals.append(info['theta'])
        ec_soil_vals.append(info['ec_soil'])
        ec_drip_vals.append(info['ec_drip'])
        et_vals.append(info['etc_mm_h'])
        irrigation_vals.append(info['irrigation_mm_h'])
        target_ec_vals.append(info['target_ec'])
        q_f_vals.append(action[0])
        q_a_vals.append(action[1])

        step_count += 1
        if use_rl and (step_count <= 10 or step_count % 20 == 0):
            logger.info(f"  step {step_count:3d}: m_w={action[0]:.3f}, dEC={action[1]:+.3f}, "
                        f"EC={info['ec_soil']:.3f}, target={info['target_ec']:.2f}, "
                        f"irr={info['irrigation_mm_h']:.3f} mm/h")

    logger.info(f"\nSimulation done! {len(time_hours)} steps ({len(time_hours):.0f} hours)")
    logger.info(f"Final: theta={theta_vals[-1]:.4f}, EC_soil={ec_soil_vals[-1]:.3f}")

    # ---- RL 动作统计 ----
    if use_rl:
        q_f_arr = np.array(q_f_vals)
        q_a_arr = np.array(q_a_vals)
        logger.info(f"\nSAC 动作统计:")
        logger.info(f"  q_f: mean={q_f_arr.mean():.4f}, std={q_f_arr.std():.4f}, "
                    f"range=[{q_f_arr.min():.4f}, {q_f_arr.max():.4f}]")
        logger.info(f"  q_a: mean={q_a_arr.mean():.4f}, std={q_a_arr.std():.4f}, "
                    f"range=[{q_a_arr.min():.4f}, {q_a_arr.max():.4f}]")

    # ====== 绘图 ======
    apply_academic_style()

    time_hours = np.array(time_hours)
    theta_vals = np.array(theta_vals)
    ec_soil_vals = np.array(ec_soil_vals)
    target_ec_vals = np.array(target_ec_vals)

    fig, axes = plt.subplots(4, 1, figsize=(9, 12), sharex=True)
    fig.subplots_adjust(hspace=0.38)

    # -- Subplot 1: Soil Moisture --
    ax = axes[0]
    style_axis(ax)
    ax.plot(time_hours, theta_vals, color=THETA, linewidth=1.5,
            label='θ (moisture)')
    ax.axhline(y=0.32, color=FC_LINE, linestyle='--', linewidth=1.0, alpha=0.8,
               label='Field capacity')
    ax.axhline(y=0.04, color=WP_LINE, linestyle=':', linewidth=1.0, alpha=0.8,
               label='Wilting point')
    set_ylim_tight(ax, theta_vals, pad_pct=5, min_val=0.0)
    ax.set_ylabel('θ (m³/m³)')
    ax.set_title(f'Root-zone soil moisture [{mode_label}]')
    ax.legend(loc='upper right', framealpha=0.55, edgecolor='#aaaaaa',
              fontsize=8.5, borderpad=0.5)

    # -- Subplot 2: EC dynamics --
    ax = axes[1]
    style_axis(ax)
    ax.plot(time_hours, ec_soil_vals, color=EC_ACTUAL, linewidth=1.5,
            label='EC_soil')
    ax.plot(time_hours, target_ec_vals, color=EC_TARGET, linestyle='--',
            linewidth=1.8, label='Target EC')
    ax.fill_between(time_hours, ec_soil_vals, target_ec_vals,
                    color='#d0d0d0', alpha=0.35, linewidth=0)
    set_ylim_tight(ax, np.concatenate([ec_soil_vals, target_ec_vals]), pad_pct=8)
    ax.set_ylabel('EC (dS/m)')
    ax.set_title(f'Root-zone EC vs target [{mode_label}]')
    ax.legend(loc='upper right', framealpha=0.55, edgecolor='#aaaaaa',
              fontsize=8.5, borderpad=0.5)

    # -- Subplot 3: Irrigation & ET --
    ax = axes[2]
    style_axis(ax)
    ax.fill_between(time_hours, 0, irrigation_vals, color=IRRIGATION,
                    alpha=0.30, linewidth=0, label='Irrigation')
    ax.plot(time_hours, et_vals, color=ET_COLOR, linewidth=2.0, linestyle='--',
            label='ET (mm/h)')
    set_ylim_tight(ax, np.concatenate([irrigation_vals, et_vals]),
                   pad_pct=10, min_val=0.0)
    ax.set_ylabel('Rate (mm/h)')
    ax.set_title(f'Irrigation and evapotranspiration [{mode_label}]')
    ax.legend(loc='upper right', framealpha=0.55, edgecolor='#aaaaaa',
              fontsize=8.5, borderpad=0.5)

    # -- Subplot 4: Actions --
    ax = axes[3]
    style_axis(ax)
    n_pts = len(time_hours)
    mk_every = max(1, n_pts // 40)
    ax.plot(time_hours, q_f_vals, color=QF, linewidth=1.2,
            marker='o', markersize=3.0, markevery=mk_every,
            label='q_f (fertilizer)')
    ax.plot(time_hours, q_a_vals, color=QA, linewidth=1.2,
            marker='^', markersize=3.5, markevery=mk_every,
            label='q_a (acid)')
    set_ylim_tight(ax, np.concatenate([q_f_vals, q_a_vals]), pad_pct=10)
    ax.set_xlabel('Time (hours)')
    ax.set_ylabel('Flow (L/min)')
    ax.set_title(f'Actions over time [{mode_label}]')
    ax.legend(loc='upper right', framealpha=0.55, edgecolor='#aaaaaa',
              fontsize=8.5, borderpad=0.5)

    fig_name = _make_output_path(mode)
    plt.savefig(fig_name, dpi=300)
    logger.info(f"\nPlot saved to: {fig_name}")
    plt.close()

    # 统计摘要
    logger.info("\n" + "=" * 60)
    logger.info("Summary Statistics")
    logger.info("=" * 60)
    logger.info(f"  Mean theta:       {theta_vals.mean():.4f} +/- {theta_vals.std():.4f}")
    logger.info(f"  Mean EC_soil:     {ec_soil_vals.mean():.3f} +/- {ec_soil_vals.std():.3f}")
    logger.info(f"  Mean irrigation:  {np.mean(irrigation_vals):.4f} mm/h")
    ec_error = np.abs(ec_soil_vals - target_ec_vals)
    logger.info(f"  EC tracking MAE:  {ec_error.mean():.3f} dS/m")


# ============================================================
#  选项 5：季节仿真对比 (T1 vs T2)
# ============================================================

def run_season_comparison(use_weather: bool = False):
    """运行完整生育期 T1 vs T2 对比仿真（基于论文 Table 9）。"""
    from digital_twin_env import DigitalTwinEnv
    from irrigation_schedule import run_season_simulation, get_irrigation_schedule

    et0_val, rain_val, from_weather = _get_weather_or_default(use_weather)

    logger.info("=" * 60)
    logger.info("马铃薯完整生育期仿真 — T1(等量) vs T2(基于根系分布)")
    logger.info("=" * 60)

    schedule = get_irrigation_schedule()
    total_irr_mm = sum(e.t1_amount_m3ha for e in schedule) / 10.0
    logger.info(f"灌溉事件: {len(schedule)} 次")
    logger.info(f"总灌溉量: {total_irr_mm:.0f} mm")
    logger.info(f"T1 单次: {schedule[0].t1_amount_m3ha:.0f} m^3/ha (等量)")
    logger.info(f"T2 单次: " + ", ".join(f"{e.t2_amount_m3ha:.0f}" for e in schedule) + " m^3/ha (变量)")
    logger.info("")

    results = {}
    for strategy in ["T1", "T2"]:
        label = "等量灌溉" if strategy == "T1" else "根系分布变量灌溉"
        logger.info(f"\n--- {strategy}: {label} ---")

        env = DigitalTwinEnv(
            growth_stage=schedule[0].growth_stage,
            area_ha=0.1,
            dt_min=15.0,
            ep_len_days=90.0,
            et0_mm_day=et0_val,
            seed=42,
        )

        res = run_season_simulation(
            env,
            model=None,
            strategy=strategy,
            area_ha=0.1,
            dt_min=15.0,
            rain_mm_day=rain_val,
            initial_theta=env.soil.theta_fc,  # 田间持水量（模拟春季底墒）
            initial_ec=0.1,
            verbose=True,
        )
        results[strategy] = res

    # ---- 对比绘图 ----
    apply_academic_style()

    col = {"T1": T1, "T2": T2}
    label_cn = {"T1": "T1 (equal)", "T2": "T2 (root-zone weighted)"}

    fig, axes = plt.subplots(4, 1, figsize=(9, 12), sharex=True)
    fig.subplots_adjust(hspace=0.38)

    for strategy in ["T1", "T2"]:
        res = results[strategy]
        c = col[strategy]
        ls = "-" if strategy == "T1" else "--"
        lbl = label_cn[strategy]

        # -- Subplot 1: theta --
        ax = axes[0]
        ax.plot(res["time_day"], res["theta"], color=c, linestyle=ls,
                linewidth=1.5, alpha=0.85, label=lbl)

        # -- Subplot 2: EC --
        ax = axes[1]
        ax.plot(res["time_day"], res["ec_soil"], color=c, linestyle=ls,
                linewidth=1.5, alpha=0.85, label=f'{lbl} EC_soil')

        # -- Subplot 3: irrigation events --
        ax = axes[2]
        event_mask = res["event_marker"] > 0.5
        ax.fill_between(res["time_day"], 0, res["irrigation_mm_h"],
                        where=event_mask, color=c, alpha=0.28,
                        linewidth=0, label=f'{lbl}')
        ax.plot(res["time_day"], res["irrigation_mm_h"], color=c,
                linewidth=0.8, alpha=0.55, drawstyle='steps-post')

        # -- Subplot 4: cumulative irrigation --
        ax = axes[3]
        cum_irr = np.cumsum(res["irrigation_mm_h"]) * (15.0 / 60.0)
        ax.plot(res["time_day"], cum_irr, color=c, linestyle=ls,
                linewidth=1.5, label=lbl)

    # ============================================================
    # Axis styling & labels
    # ============================================================

    # Subplot 1: theta
    ax = axes[0]
    style_axis(ax)
    ax.axhline(y=0.32, color=FC_LINE, linestyle='--', linewidth=0.8, alpha=0.6)
    ax.axhline(y=0.04, color=WP_LINE, linestyle=':', linewidth=0.8, alpha=0.6)
    all_theta = np.concatenate([results["T1"]["theta"], results["T2"]["theta"]])
    set_ylim_tight(ax, all_theta, pad_pct=5, min_val=0.0)
    ax.set_ylabel('θ (m³/m³)')
    ax.set_title('Root-zone soil moisture — T1 vs T2')
    ax.legend(loc='upper right', framealpha=0.55, edgecolor='#aaaaaa',
              fontsize=8.5, borderpad=0.5)

    # Subplot 2: EC
    ax = axes[1]
    style_axis(ax)
    t1 = results["T1"]
    ax.plot(t1["time_day"], t1["target_ec"], color='#333333', linestyle=':',
            linewidth=1.2, alpha=0.7, label='Target EC')
    all_ec = np.concatenate([results["T1"]["ec_soil"], results["T2"]["ec_soil"],
                             t1["target_ec"]])
    set_ylim_tight(ax, all_ec, pad_pct=8)
    ax.set_ylabel('EC (dS/m)')
    ax.set_title('Root-zone EC dynamics — T1 vs T2')
    ax.legend(loc='upper right', framealpha=0.55, edgecolor='#aaaaaa',
              fontsize=8.5, borderpad=0.5)

    # Subplot 3: irrigation events
    ax = axes[2]
    style_axis(ax)
    all_irr = np.concatenate([results["T1"]["irrigation_mm_h"],
                              results["T2"]["irrigation_mm_h"]])
    set_ylim_tight(ax, all_irr, pad_pct=10, min_val=0.0)
    ax.set_ylabel('Irrigation (mm/h)')
    ax.set_title('Irrigation event sequence')
    ax.legend(loc='upper right', framealpha=0.55, edgecolor='#aaaaaa',
              fontsize=8.5, borderpad=0.5)

    # Subplot 4: cumulative irrigation
    ax = axes[3]
    style_axis(ax)
    ax.set_xlabel('Days after emergence')
    ax.set_ylabel('Cumulative irrigation (mm)')
    ax.set_title('Cumulative irrigation')
    ax.legend(loc='upper right', framealpha=0.55, edgecolor='#aaaaaa',
              fontsize=8.5, borderpad=0.5)

    fig_path = _make_output_path("5")
    plt.savefig(fig_path, dpi=300)
    logger.info(f"\n对比图已保存: {fig_path}")
    plt.close()

    # ---- 统计对比 ----
    logger.info("\n" + "=" * 60)
    logger.info("T1 vs T2 统计对比（论文关键指标）")
    logger.info("=" * 60)
    logger.info(f"{'指标':<30} {'T1 (等量)':>12} {'T2 (根系)':>12} {'改善':>8}")
    logger.info("-" * 62)

    t1 = results["T1"]
    t2 = results["T2"]

    # EC 跟踪 MAE
    ec_mae_t1 = np.abs(t1["ec_soil"] - t1["target_ec"]).mean()
    ec_mae_t2 = np.abs(t2["ec_soil"] - t2["target_ec"]).mean()
    logger.info(f"  EC tracking MAE (dS/m)       {ec_mae_t1:12.3f} {ec_mae_t2:12.3f}")

    # 平均含水率
    theta_t1 = t1["theta"].mean()
    theta_t2 = t2["theta"].mean()
    improvement = (theta_t2 - theta_t1) / (theta_t1 + 1e-6) * 100
    logger.info(f"  平均 theta                    {theta_t1:12.4f} {theta_t2:12.4f} {improvement:+7.1f}%")

    # 总灌溉量
    logger.info(f"  总灌溉量 (mm)                {t1['total_irrigation_mm']:12.1f} {t2['total_irrigation_mm']:12.1f}")

    # 总蒸散发（高 = 作物蒸腾更多 = 生长更好）
    logger.info(f"  总蒸散发 (mm)                {t1['total_etc_mm']:12.1f} {t2['total_etc_mm']:12.1f}")

    # 灌溉后 theta 稳定度（标准差越小越稳定）
    # 只统计灌溉事件期间的数据
    t1_event = t1["theta"][t1["event_marker"] > 0.5]
    t2_event = t2["theta"][t2["event_marker"] > 0.5]
    if len(t1_event) > 0 and len(t2_event) > 0:
        cv_t1 = t1_event.std() / (t1_event.mean() + 1e-6)
        cv_t2 = t2_event.std() / (t2_event.mean() + 1e-6)
        logger.info(f"  灌溉期 theta CV               {cv_t1:12.4f} {cv_t2:12.4f}")

    # 深层渗漏估算 (theta > FC 期间的排水)
    drain_t1 = np.maximum(0, t1["theta"] - 0.32).sum() * 15.3  # K_sat × excess
    drain_t2 = np.maximum(0, t2["theta"] - 0.32).sum() * 15.3
    logger.info(f"  深层渗漏估算 (mm)            {drain_t1:12.1f} {drain_t2:12.1f}")

    # WUE 代理 (ET / 总耗水)
    wue_t1 = t1["total_etc_mm"] / (t1["total_irrigation_mm"] + 2.5 * 65 + 1e-6)
    wue_t2 = t2["total_etc_mm"] / (t2["total_irrigation_mm"] + 2.5 * 65 + 1e-6)
    logger.info(f"  WUE 代理 (ET/总入流)          {wue_t1:12.4f} {wue_t2:12.4f}")

    # 论文期望: T2 水分利用效率提高 14%-19%
    wue_change = (wue_t2 - wue_t1) / (wue_t1 + 1e-6) * 100
    logger.info(f"\n  → 论文 WUE 提升: 14%-19%")
    logger.info(f"  → 当前模型 WUE 变化: {wue_change:+.1f}%")


# ============================================================
#  启动菜单
# ============================================================

def show_menu():
    """显示交互式启动菜单。"""
    logger.info("")
    logger.info("=" * 50)
    logger.info("  马铃薯施肥灌溉数字孪生系统")
    logger.info("=" * 50)
    logger.info("  1. 仿真运行（固定策略）")
    logger.info("  2. 仿真运行（SAC 动态控制）")
    logger.info("  3. 训练 SAC 模型（支持断点续训）")
    logger.info("  4. 查看训练进度")
    logger.info("  5. 季节仿真 T1 vs T2 对比")
    logger.info("  6. SAC 闭环评估（全生育期）")
    logger.info("  0. 退出")
    logger.info("=" * 50)

    choice = input("  请选择 [0-6]: ").strip()
    return choice


def _find_python():
    """优先返回 conda 环境 Python，否则返回当前 Python。"""
    candidates = [
        r"C:\Users\Administrator\.conda\envs\digital-twin\python.exe",
        r"C:\Users\Administrator\miniconda3\envs\digital-twin\python.exe",
        r"C:\Users\Administrator\anaconda3\envs\digital-twin\python.exe",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return sys.executable

_PYTHON = _find_python()

def run_script(script_name: str, args: list = None):
    """通过 subprocess 运行另一个 Python 脚本。"""
    script_path = os.path.join(os.path.dirname(__file__), script_name)
    cmd = [_PYTHON, script_path]
    if args:
        cmd.extend(args)
    logger.info(f"\n>>> 启动: {' '.join(cmd)}\n")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        logger.error(f"\n[WARN] {script_name} 退出码: {result.returncode}")
    return result.returncode


# ============================================================
#  主入口
# ============================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="数字孪生系统启动器")
    parser.add_argument("--mode", type=int, choices=range(0, 7),
                        help="直接指定模式（0=退出, 1=固定, 2=SAC, "
                             "3=训练SAC, 4=查看训练, 5=T1vsT2, 6=SAC评估）")
    parser.add_argument("--weather", action="store_true",
                        help="使用察右中旗真实天气数据 (Open-Meteo)")
    args = parser.parse_args()

    if args.mode is not None:
        mode = str(args.mode)
        logger.info("")
        if mode == "1":
            run_simulation(model_type="none", mode="1", use_weather=args.weather)
        elif mode == "2":
            run_simulation(model_type="sac", mode="2", use_weather=args.weather)
        elif mode == "3":
            resume = input("  从上次模型继续训练? [y/N]: ").strip().lower() == "y"
            run_script("train_sac.py", ["--resume"] if resume else [])
        elif mode == "4":
            run_script("check_training.py")
        elif mode == "5":
            run_season_comparison(use_weather=args.weather)
        elif mode == "6":
            run_script("eval_sac.py")
        elif mode == "0":
            logger.info("再见！")
        else:
            logger.error(f"[ERROR] 无效选项: {mode}")
            sys.exit(1)
    else:
        try:
          while True:
            mode = show_menu()
            logger.info("")

            if mode == "1":
                run_simulation(model_type="none", mode="1", use_weather=args.weather)
            elif mode == "2":
                run_simulation(model_type="sac", mode="2", use_weather=args.weather)
            elif mode == "3":
                resume = input("\n  从上次模型继续训练? [y/N]: ").strip().lower() == "y"
                run_script("train_sac.py", ["--resume"] if resume else [])
            elif mode == "4":
                run_script("check_training.py")
            elif mode == "5":
                run_season_comparison(use_weather=args.weather)
            elif mode == "6":
                run_script("eval_sac.py")
            elif mode == "0":
                logger.info("再见！")
                break
            else:
                logger.error(f"[ERROR] 无效选项: {mode}")

            input("\n按 Enter 键返回菜单...")
        except KeyboardInterrupt:
            logger.info("\n再见！")

