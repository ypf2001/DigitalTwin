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
import os
import subprocess
import sys
from datetime import datetime
from config_loader import load_config
from weather_client import get_et0_rain

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
        print(f"[天气] 察右中旗 今日 ET0={et0:.1f} mm/天, 降雨={rain:.1f} mm/天")
        return et0, rain, True
    except Exception as e:
        print(f"[天气] 获取失败 ({e})，回退到 config.yaml 默认值")
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

    print("=" * 60)
    print("Potato Fertigation Digital Twin - Simulation")
    print("=" * 60)

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
        model_path = "rl_models/sac_mid_final"

        if os.path.exists(model_path + ".zip"):
            model = RLModel.load(model_path)
            print(f"[SAC] 模型加载: {model_path}")
        else:
            print(f"[WARN] 模型 {model_path}.zip 不存在，回退到固定策略")
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
    print(f"Observation dim: {len(obs)}")
    print(f"Control mode: {mode_labels.get(model_type, model_type)}")

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

    print("\nRunning simulation (5 days)...")
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
            print(f"  step {step_count:3d}: q_f={action[0]:.4f}, q_a={action[1]:.4f}, "
                  f"EC={info['ec_soil']:.3f}, target={info['target_ec']:.2f}, "
                  f"irr={info['irrigation_mm_h']:.3f} mm/h")

    print(f"\nSimulation done! {len(time_hours)} steps ({len(time_hours):.0f} hours)")
    print(f"Final: theta={theta_vals[-1]:.4f}, EC_soil={ec_soil_vals[-1]:.3f}")

    # ---- RL 动作统计 ----
    if use_rl:
        q_f_arr = np.array(q_f_vals)
        q_a_arr = np.array(q_a_vals)
        print(f"\nSAC 动作统计:")
        print(f"  q_f: mean={q_f_arr.mean():.4f}, std={q_f_arr.std():.4f}, "
              f"range=[{q_f_arr.min():.4f}, {q_f_arr.max():.4f}]")
        print(f"  q_a: mean={q_a_arr.mean():.4f}, std={q_a_arr.std():.4f}, "
              f"range=[{q_a_arr.min():.4f}, {q_a_arr.max():.4f}]")

    # ====== 绘图 ======
    fig, axes = plt.subplots(4, 1, figsize=(12, 13), sharex=True)

    time_hours = np.array(time_hours)
    theta_vals = np.array(theta_vals)
    ec_soil_vals = np.array(ec_soil_vals)
    target_ec_vals = np.array(target_ec_vals)

    # 图1: Soil Moisture
    ax1 = axes[0]
    ax1.plot(time_hours, theta_vals, 'b-', linewidth=1.5, label='θ (moisture)')
    ax1.axhline(y=0.32, color='gray', linestyle='--', alpha=0.7, label='Field Capacity')
    ax1.axhline(y=0.04, color='r', linestyle=':', alpha=0.5, label='Wilting Point')
    ax1.set_ylabel('θ (m3/m3)')
    ax1.set_title(f'Root Zone Soil Moisture [{mode_label}]')
    ax1.legend(loc='best')
    ax1.grid(True, alpha=0.3)
    ax1.set_ylim(0.0, 0.50)

    # 图2: EC dynamics
    ax2 = axes[1]
    ax2.plot(time_hours, ec_soil_vals, 'r-', linewidth=1.5, label='EC_soil')
    ax2.plot(time_hours, target_ec_vals, 'g--', linewidth=1.5, label='Target EC')
    ax2.set_ylabel('EC (dS/m)')
    ax2.set_title(f'Root Zone EC vs Target [{mode_label}]')
    ax2.legend(loc='best')
    ax2.grid(True, alpha=0.3)

    # 图3: Irrigation & ET
    ax3 = axes[2]
    ax3.plot(time_hours, irrigation_vals, 'b-', linewidth=1.0, alpha=0.7, label='Irrigation')
    ax3.plot(time_hours, et_vals, 'orange', linewidth=1.5, label='ET (mm/h)')
    ax3.set_ylabel('Rate (mm/h)')
    ax3.set_title(f'Irrigation and Evapotranspiration [{mode_label}]')
    ax3.legend(loc='best')
    ax3.grid(True, alpha=0.3)

    # 图4: 动作变化
    ax4 = axes[3]
    ax4.plot(time_hours, q_f_vals, 'g-', linewidth=1.5, label='q_f (母液)')
    ax4.plot(time_hours, q_a_vals, 'm-', linewidth=1.5, label='q_a (酸液)')
    ax4.set_xlabel('Time (hours)')
    ax4.set_ylabel('Flow (L/min)')
    ax4.set_title(f'Actions over Time [{mode_label}]')
    ax4.legend(loc='best')
    ax4.grid(True, alpha=0.3)

    plt.tight_layout()
    fig_name = _make_output_path(mode)
    plt.savefig(fig_name, dpi=150)
    print(f"\nPlot saved to: {fig_name}")
    plt.close()

    # 统计摘要
    print("\n" + "=" * 60)
    print("Summary Statistics")
    print("=" * 60)
    print(f"  Mean theta:       {theta_vals.mean():.4f} +/- {theta_vals.std():.4f}")
    print(f"  Mean EC_soil:     {ec_soil_vals.mean():.3f} +/- {ec_soil_vals.std():.3f}")
    print(f"  Mean irrigation:  {np.mean(irrigation_vals):.4f} mm/h")
    ec_error = np.abs(ec_soil_vals - target_ec_vals)
    print(f"  EC tracking MAE:  {ec_error.mean():.3f} dS/m")


# ============================================================
#  选项 5：季节仿真对比 (T1 vs T2)
# ============================================================

def run_season_comparison(use_weather: bool = False):
    """运行完整生育期 T1 vs T2 对比仿真（基于论文 Table 9）。"""
    from digital_twin_env import DigitalTwinEnv
    from irrigation_schedule import run_season_simulation, get_irrigation_schedule

    et0_val, rain_val, from_weather = _get_weather_or_default(use_weather)

    print("=" * 60)
    print("马铃薯完整生育期仿真 — T1(等量) vs T2(基于根系分布)")
    print("=" * 60)

    schedule = get_irrigation_schedule()
    total_irr_mm = sum(e.t1_amount_m3ha for e in schedule) / 10.0
    print(f"灌溉事件: {len(schedule)} 次")
    print(f"总灌溉量: {total_irr_mm:.0f} mm")
    print(f"T1 单次: {schedule[0].t1_amount_m3ha:.0f} m^3/ha (等量)")
    print(f"T2 单次: " + ", ".join(f"{e.t2_amount_m3ha:.0f}" for e in schedule) + " m^3/ha (变量)")
    print()

    results = {}
    for strategy in ["T1", "T2"]:
        label = "等量灌溉" if strategy == "T1" else "根系分布变量灌溉"
        print(f"\n--- {strategy}: {label} ---")

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
    fig, axes = plt.subplots(4, 1, figsize=(14, 14), sharex=True)

    colors = {"T1": "blue", "T2": "red"}

    for idx, (label, res) in enumerate(results.items()):
        c = colors[label]
        style = "-" if label == "T1" else "--"

        # theta
        axes[0].plot(res["time_day"], res["theta"], color=c, linestyle=style,
                     linewidth=1.5, alpha=0.8, label=f"{label}")
        # EC
        axes[1].plot(res["time_day"], res["ec_soil"], color=c, linestyle=style,
                     linewidth=1.5, alpha=0.8, label=f"{label} EC_soil")
        # irrigation
        event_mask = res["event_marker"] > 0.5
        axes[2].fill_between(res["time_day"], 0, res["irrigation_mm_h"],
                             where=event_mask, color=c, alpha=0.3, label=f"{label} 灌溉")
        axes[2].plot(res["time_day"], res["irrigation_mm_h"], color=c,
                     linewidth=0.8, alpha=0.6, drawstyle='steps-post')
        # cumulative
        cum_irr = np.cumsum(res["irrigation_mm_h"]) * (15.0 / 60.0)
        axes[3].plot(res["time_day"], cum_irr, color=c, linestyle=style,
                     linewidth=1.5, label=f"{label} 累计灌溉")

    # 标注
    axes[0].set_ylabel('theta (m3/m3)')
    axes[0].set_title('根区含水率 — T1 vs T2')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(results["T1"]["time_day"], results["T1"]["target_ec"],
                 'k:', linewidth=1, alpha=0.5, label='Target EC')
    axes[1].set_ylabel('EC (dS/m)')
    axes[1].set_title('根区 EC 动态 — T1 vs T2')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    axes[2].set_ylabel('灌溉 (mm/h)')
    axes[2].set_title('灌溉事件时序')
    axes[2].legend()
    axes[2].grid(True, alpha=0.3)

    axes[3].set_xlabel('出苗后天数')
    axes[3].set_ylabel('累计灌溉 (mm)')
    axes[3].set_title('累计灌溉量')
    axes[3].legend()
    axes[3].grid(True, alpha=0.3)

    plt.tight_layout()
    fig_path = _make_output_path("5")
    plt.savefig(fig_path, dpi=150)
    print(f"\n对比图已保存: {fig_path}")
    plt.close()

    # ---- 统计对比 ----
    print("\n" + "=" * 60)
    print("T1 vs T2 统计对比（论文关键指标）")
    print("=" * 60)
    print(f"{'指标':<30} {'T1 (等量)':>12} {'T2 (根系)':>12} {'改善':>8}")
    print("-" * 62)

    t1 = results["T1"]
    t2 = results["T2"]

    # EC 跟踪 MAE
    ec_mae_t1 = np.abs(t1["ec_soil"] - t1["target_ec"]).mean()
    ec_mae_t2 = np.abs(t2["ec_soil"] - t2["target_ec"]).mean()
    print(f"  EC tracking MAE (dS/m)       {ec_mae_t1:12.3f} {ec_mae_t2:12.3f}")

    # 平均含水率
    theta_t1 = t1["theta"].mean()
    theta_t2 = t2["theta"].mean()
    improvement = (theta_t2 - theta_t1) / (theta_t1 + 1e-6) * 100
    print(f"  平均 theta                    {theta_t1:12.4f} {theta_t2:12.4f} {improvement:+7.1f}%")

    # 总灌溉量
    print(f"  总灌溉量 (mm)                {t1['total_irrigation_mm']:12.1f} {t2['total_irrigation_mm']:12.1f}")

    # 总蒸散发（高 = 作物蒸腾更多 = 生长更好）
    print(f"  总蒸散发 (mm)                {t1['total_etc_mm']:12.1f} {t2['total_etc_mm']:12.1f}")

    # 灌溉后 theta 稳定度（标准差越小越稳定）
    # 只统计灌溉事件期间的数据
    t1_event = t1["theta"][t1["event_marker"] > 0.5]
    t2_event = t2["theta"][t2["event_marker"] > 0.5]
    if len(t1_event) > 0 and len(t2_event) > 0:
        cv_t1 = t1_event.std() / (t1_event.mean() + 1e-6)
        cv_t2 = t2_event.std() / (t2_event.mean() + 1e-6)
        print(f"  灌溉期 theta CV               {cv_t1:12.4f} {cv_t2:12.4f}")

    # 深层渗漏估算 (theta > FC 期间的排水)
    drain_t1 = np.maximum(0, t1["theta"] - 0.32).sum() * 15.3  # K_sat × excess
    drain_t2 = np.maximum(0, t2["theta"] - 0.32).sum() * 15.3
    print(f"  深层渗漏估算 (mm)            {drain_t1:12.1f} {drain_t2:12.1f}")

    # WUE 代理 (ET / 总耗水)
    wue_t1 = t1["total_etc_mm"] / (t1["total_irrigation_mm"] + 2.5 * 65 + 1e-6)
    wue_t2 = t2["total_etc_mm"] / (t2["total_irrigation_mm"] + 2.5 * 65 + 1e-6)
    print(f"  WUE 代理 (ET/总入流)          {wue_t1:12.4f} {wue_t2:12.4f}")

    # 论文期望: T2 水分利用效率提高 14%-19%
    wue_change = (wue_t2 - wue_t1) / (wue_t1 + 1e-6) * 100
    print(f"\n  → 论文 WUE 提升: 14%-19%")
    print(f"  → 当前模型 WUE 变化: {wue_change:+.1f}%")


# ============================================================
#  启动菜单
# ============================================================

def show_menu():
    """显示交互式启动菜单。"""
    print()
    print("=" * 50)
    print("  马铃薯施肥灌溉数字孪生系统")
    print("=" * 50)
    print("  1. 仿真运行（固定策略）")
    print("  2. 仿真运行（SAC 动态控制）")
    print("  3. 训练 SAC 模型")
    print("  4. 查看训练进度")
    print("  5. 季节仿真 T1 vs T2 对比")
    print("  0. 退出")
    print("=" * 50)

    choice = input("  请选择 [0-5]: ").strip()
    return choice


def run_script(script_name: str, args: list = None):
    """通过 subprocess 运行另一个 Python 脚本。"""
    python = sys.executable
    script_path = os.path.join(os.path.dirname(__file__), script_name)
    cmd = [python, script_path]
    if args:
        cmd.extend(args)
    print(f"\n>>> 启动: {' '.join(cmd)}\n")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"\n[WARN] {script_name} 退出码: {result.returncode}")
    return result.returncode


# ============================================================
#  主入口
# ============================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="数字孪生系统启动器")
    parser.add_argument("--mode", type=int, choices=range(0, 6),
                        help="直接指定模式（0=退出, 1=固定, 2=SAC, "
                             "3=训练SAC, 4=查看训练, 5=T1vsT2）")
    parser.add_argument("--weather", action="store_true",
                        help="使用察右中旗真实天气数据 (Open-Meteo)")
    args = parser.parse_args()

    if args.mode is not None:
        mode = str(args.mode)
        print()
        if mode == "1":
            run_simulation(model_type="none", mode="1", use_weather=args.weather)
        elif mode == "2":
            run_simulation(model_type="sac", mode="2", use_weather=args.weather)
        elif mode == "3":
            run_script("train_sac.py")
        elif mode == "4":
            run_script("check_training.py")
        elif mode == "5":
            run_season_comparison(use_weather=args.weather)
        elif mode == "0":
            print("再见！")
        else:
            print(f"[ERROR] 无效选项: {mode}")
            sys.exit(1)
    else:
        try:
          while True:
            mode = show_menu()
            print()

            if mode == "1":
                run_simulation(model_type="none", mode="1", use_weather=args.weather)
            elif mode == "2":
                run_simulation(model_type="sac", mode="2", use_weather=args.weather)
            elif mode == "3":
                run_script("train_sac.py")
            elif mode == "4":
                run_script("check_training.py")
            elif mode == "5":
                run_season_comparison(use_weather=args.weather)
            elif mode == "0":
                print("再见！")
                break
            else:
                print(f"[ERROR] 无效选项: {mode}")

            input("\n按 Enter 键返回菜单...")
        except KeyboardInterrupt:
            print("\n再见！")
