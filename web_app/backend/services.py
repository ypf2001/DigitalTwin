"""业务逻辑层 — 仿真、季节对比、天气、配置"""

import os
import traceback

import numpy as np
import yaml

from config_loader import load_config, reload_config

# 配置项 → YAML 文件 映射
_SECTION_FILE_MAP = {
    "crop": "crop.yaml",
    "irrigation": "irrigation.yaml",
    "reward": "reward.yaml",
    "sac": "training.yaml",
}
# simulation.yaml 包含多个顶层 key
_SIMULATION_KEYS = {"env", "soil", "mixing_tank", "pipe", "action", "obs", "day_night", "plc"}


def _get_config_dir():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config")


def get_weather_data(use_weather: bool = True):
    """返回天气数据 (et0, rain_mm_day, from_weather)"""
    if not use_weather:
        env_cfg = load_config().env()
        irr_cfg = load_config().irrigation()
        return env_cfg["et0_mm_day"], irr_cfg.get("rain_mm_day", 2.0), False
    try:
        from weather_client import get_et0_rain
        et0, rain = get_et0_rain()
        return et0, rain, True
    except Exception:
        env_cfg = load_config().env()
        irr_cfg = load_config().irrigation()
        return env_cfg["et0_mm_day"], irr_cfg.get("rain_mm_day", 2.0), False


def get_config_data():
    """返回系统配置摘要"""
    cfg = load_config()
    return {
        "stages": cfg.crop_stages(),
        "soil": {
            "theta_fc": cfg.get("env.theta_fc"),
            "theta_wp": cfg.get("env.theta_wp"),
            "theta_init": cfg.get("env.theta_init"),
            "ec_init": cfg.get("env.ec_init"),
        },
        "mixing_tank": cfg.mixing_tank(),
        "pipe": cfg.pipe(),
        "action_fixed": cfg.action().get("fixed_strategy", [5.0, 1.0]),
        "reward": cfg.reward(),
        "sac": cfg.sac(),
        "irrigation": cfg.irrigation(),
    }


def run_simulation(mode: str, stage_key: str, use_weather: bool):
    """运行 5 天短时仿真，返回时间序列 + 统计"""
    from digital_twin_env import DigitalTwinEnv
    from digital_twin_gym_env import DigitalTwinGymEnv
    from crop_model import GrowthStage

    smap = {
        "EMERGENCE": GrowthStage.EMERGENCE,
        "VEGETATIVE": GrowthStage.VEGETATIVE,
        "TUBER_INIT": GrowthStage.TUBER_INIT,
        "BULKING": GrowthStage.BULKING,
        "STARCH_ACCUMULATION": GrowthStage.STARCH_ACCUMULATION,
        "MATURATION": GrowthStage.MATURATION,
    }
    stage = smap.get(stage_key, GrowthStage.BULKING)
    et0_val, _, from_weather = get_weather_data(use_weather)

    use_rl = (mode == "sac")
    model = None
    if use_rl:
        env = DigitalTwinGymEnv(
            growth_stage="MID", area_ha=0.1, dt_min=60.0,
            ep_len_days=5.0, et0_mm_day=et0_val,
        )
        obs, _ = env.reset()
        from stable_baselines3 import SAC
        mp = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'rl_models', 'sac_mid_final',
        )
        if os.path.exists(mp + ".zip"):
            model = SAC.load(mp)
        else:
            use_rl = False
    else:
        env = DigitalTwinEnv(
            growth_stage=stage, area_ha=0.1, dt_min=60.0,
            ep_len_days=5.0, et0_mm_day=et0_val,
        )
        obs = env.reset()

    th, tl, ecl, edl, etl, irl, tcl, qfl, qal = [], [], [], [], [], [], [], [], []
    done = False
    while not done:
        if use_rl and model is not None:
            action, _ = model.predict(obs, deterministic=True)
        else:
            action = np.array(load_config().action()["fixed_strategy"], dtype=np.float32)

        if hasattr(env, 'action_space'):
            obs, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated
        else:
            obs, reward, done, info = env.step(action)

        th.append(float(info['time_day'] * 24.0))
        tl.append(float(info['theta']))
        ecl.append(float(info['ec_soil']))
        edl.append(float(info['ec_drip']))
        etl.append(float(info['etc_mm_h']))
        irl.append(float(info['irrigation_mm_h']))
        tcl.append(float(info['target_ec']))
        qfl.append(float(action[0]))
        qal.append(float(action[1]))

    ec, tec, irr = np.array(ecl), np.array(tcl), np.array(irl)
    return {
        "success": True, "mode": mode, "stage": stage_key,
        "weather": from_weather, "steps": len(th),
        "series": {
            "time_hours": [round(v, 1) for v in th],
            "theta": [round(v, 4) for v in tl],
            "ec_soil": [round(v, 3) for v in ecl],
            "ec_drip": [round(v, 3) for v in edl],
            "ec_target": [round(v, 3) for v in tcl],
            "etc_mm_h": [round(v, 4) for v in etl],
            "irrigation_mm_h": [round(v, 4) for v in irl],
            "q_f": [round(v, 4) for v in qfl],
            "q_a": [round(v, 4) for v in qal],
        },
        "stats": {
            "theta_mean": round(float(np.mean(tl)), 4),
            "theta_final": round(float(tl[-1]), 4),
            "ec_soil_final": round(float(ecl[-1]), 3),
            "ec_mae": round(float(np.abs(ec - tec).mean()), 3),
            "total_irrigation_mm": round(float(irr.sum()), 2),
            "total_et_mm": round(float(np.sum(etl)), 2),
            "q_f_mean": round(float(np.mean(qfl)), 4),
            "q_a_mean": round(float(np.mean(qal)), 4),
        },
    }


def run_season_compare(use_weather: bool):
    """运行 T1 vs T2 完整生育期对比仿真"""
    from digital_twin_env import DigitalTwinEnv
    from irrigation_schedule import run_season_simulation, get_irrigation_schedule

    et0_val, rain_val, from_weather = get_weather_data(use_weather)
    schedule = get_irrigation_schedule()
    results = {}
    for strategy in ["T1", "T2"]:
        env = DigitalTwinEnv(
            growth_stage=schedule[0].growth_stage, area_ha=0.1,
            dt_min=15.0, ep_len_days=90.0, et0_mm_day=et0_val, seed=42,
        )
        res = run_season_simulation(
            env, model=None, strategy=strategy, area_ha=0.1, dt_min=15.0,
            rain_mm_day=rain_val, initial_theta=env.soil.theta_fc,
            initial_ec=0.1, verbose=False,
        )
        results[strategy] = res

    def _r(a, n=4):
        return [round(float(v), n) for v in a]

    t1, t2 = results["T1"], results["T2"]
    em1 = float(np.abs(t1["ec_soil"] - t1["target_ec"]).mean())
    em2 = float(np.abs(t2["ec_soil"] - t2["target_ec"]).mean())
    wue1 = float(t1["total_etc_mm"]) / (float(t1["total_irrigation_mm"]) + 162.5 + 1e-6)
    wue2 = float(t2["total_etc_mm"]) / (float(t2["total_irrigation_mm"]) + 162.5 + 1e-6)
    dr1 = float(np.maximum(0, t1["theta"] - 0.32).sum() * 15.3)
    dr2 = float(np.maximum(0, t2["theta"] - 0.32).sum() * 15.3)
    t1e = t1["theta"][t1["event_marker"] > 0.5]
    t2e = t2["theta"][t2["event_marker"] > 0.5]
    cv1 = float(t1e.std() / (t1e.mean() + 1e-6)) if len(t1e) > 0 else 0
    cv2 = float(t2e.std() / (t2e.mean() + 1e-6)) if len(t2e) > 0 else 0

    return {
        "success": True, "weather": from_weather,
        "T1": {k: _r(t1[k]) for k in ["time_day", "theta", "ec_soil", "target_ec",
                                         "irrigation_mm_h", "etc_mm_h", "event_marker"]},
        "T2": {k: _r(t2[k]) for k in ["time_day", "theta", "ec_soil", "target_ec",
                                         "irrigation_mm_h", "etc_mm_h", "event_marker"]},
        "stats": {
            "ec_mae_t1": round(em1, 3), "ec_mae_t2": round(em2, 3),
            "theta_mean_t1": round(float(t1["theta"].mean()), 4),
            "theta_mean_t2": round(float(t2["theta"].mean()), 4),
            "theta_improve_pct": round(
                (float(t2["theta"].mean()) - float(t1["theta"].mean()))
                / (float(t1["theta"].mean()) + 1e-6) * 100, 1),
            "total_irr_t1": round(float(t1["total_irrigation_mm"]), 1),
            "total_irr_t2": round(float(t2["total_irrigation_mm"]), 1),
            "total_et_t1": round(float(t1["total_etc_mm"]), 1),
            "total_et_t2": round(float(t2["total_etc_mm"]), 1),
            "deep_drain_t1": round(dr1, 1), "deep_drain_t2": round(dr2, 1),
            "theta_cv_t1": round(cv1, 4), "theta_cv_t2": round(cv2, 4),
            "wue_t1": round(wue1, 4), "wue_t2": round(wue2, 4),
            "wue_change_pct": round((wue2 - wue1) / (wue1 + 1e-6) * 100, 1),
        },
    }


def save_config_section(section: str, updates: dict):
    """保存配置段到对应的 YAML 文件，支持嵌套键路径如 'crop.stages.bulking.target_ec'。

    参数
    ----------
    section : str
        'crop' / 'irrigation' / 'reward' / 'sac' 或 'simulation'
    updates : dict
        {'key.path': new_value, ...}
    """
    config_dir = _get_config_dir()

    # 确定文件名
    if section == "simulation":
        filename = "simulation.yaml"
    else:
        filename = _SECTION_FILE_MAP.get(section)
    if not filename:
        raise ValueError(f"未知配置段: {section}")

    filepath = os.path.join(config_dir, filename)
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"配置文件不存在: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # 按点号路径设置值
    for key_path, value in updates.items():
        parts = key_path.split(".")
        node = data
        for i, part in enumerate(parts[:-1]):
            if part not in node:
                node[part] = {}
            node = node[part]
        # 尝试类型转换
        old_val = node.get(parts[-1])
        if isinstance(old_val, float) or (isinstance(old_val, int) and isinstance(value, str) and "." in value):
            try:
                value = float(value)
            except (ValueError, TypeError):
                pass
        elif isinstance(old_val, int):
            try:
                value = int(value)
            except (ValueError, TypeError):
                pass
        elif isinstance(old_val, bool):
            value = value if isinstance(value, bool) else str(value).lower() in ("true", "1", "yes")
        node[parts[-1]] = value

    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    reload_config()
    return {"success": True, "section": section}

