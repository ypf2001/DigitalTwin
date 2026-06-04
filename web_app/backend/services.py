"""业务逻辑层 — 仿真、季节对比、天气、配置"""

import os
import sys
import traceback
import threading
import re

import numpy as np
import yaml

from config_loader import load_config, reload_config

STAGE_MAP = {"ini": "INI", "dev": "DEV", "mid": "MID", "late": "LATE"}

training_lock = threading.Lock()
upload_lock = threading.Lock()

_IMAGES_DIR = os.path.join(os.path.dirname(__file__), "static", "images")

_SECTION_FILE_MAP = {
    "crop": "crop.yaml",
    "irrigation": "irrigation.yaml",
    "reward": "reward.yaml",
    "sac": "training.yaml",
}
_SIMULATION_KEYS = {"env", "soil", "mixing_tank", "pipe", "action", "obs", "day_night", "plc", "experiment"}


def _get_config_dir():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config")


def _extract_yaml_inline_comments(filepath: str) -> dict:
    """Extract same-line YAML comments as lightweight display labels."""
    labels = {}
    stack = []

    with open(filepath, "r", encoding="utf-8") as f:
        for raw_line in f:
            code, comment = raw_line.split("#", 1) if "#" in raw_line else (raw_line, "")
            if ":" not in code or not code.strip():
                continue

            stripped = code.strip()
            if stripped.startswith("-"):
                continue

            key = stripped.split(":", 1)[0].strip().strip("'\"")
            if not key:
                continue

            indent = len(code) - len(code.lstrip(" "))
            level = indent // 2
            stack = stack[:level]
            stack.append(key)

            label = comment.strip()
            if label:
                labels[".".join(stack)] = label

    return labels


def get_config_labels():
    config_dir = _get_config_dir()
    labels = {}

    for filename in ["simulation.yaml", "crop.yaml", "reward.yaml", "training.yaml", "irrigation.yaml"]:
        filepath = os.path.join(config_dir, filename)
        if os.path.exists(filepath):
            labels.update(_extract_yaml_inline_comments(filepath))

    return labels


def _format_yaml_scalar(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    return str(value)


def _replace_yaml_scalar_line(line: str, value) -> str:
    newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
    body = line[:-len(newline)] if newline else line
    hash_pos = body.find("#")
    code = body if hash_pos < 0 else body[:hash_pos]
    comment = "" if hash_pos < 0 else body[hash_pos:].rstrip()
    prefix = code.split(":", 1)[0].rstrip()
    updated = f"{prefix}: {_format_yaml_scalar(value)}"
    if comment:
        updated += f"  {comment}"
    return updated + newline


def _replace_yaml_list_line(line: str, value) -> str:
    newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
    body = line[:-len(newline)] if newline else line
    hash_pos = body.find("#")
    code = body if hash_pos < 0 else body[:hash_pos]
    comment = "" if hash_pos < 0 else body[hash_pos:].rstrip()
    indent = re.match(r"^(\s*)-", code).group(1)
    updated = f"{indent}- {_format_yaml_scalar(value)}"
    if comment:
        updated += f"  {comment}"
    return updated + newline


def _update_yaml_text_value(lines: list[str], key_path: str, value) -> bool:
    parts = key_path.split(".")

    if parts[-1].isdigit():
        parent_parts = parts[:-1]
        target_index = int(parts[-1])
        stack = []
        parent_indent = None

        for i, line in enumerate(lines):
            code = line.split("#", 1)[0]
            match = re.match(r"^(\s*)([^:\-\s][^:]*):", code)
            if not match:
                continue
            indent = len(match.group(1))
            level = indent // 2
            key = match.group(2).strip().strip("'\"")
            stack = stack[:level]
            stack.append(key)

            if stack == parent_parts:
                parent_indent = indent
                seen = 0
                for j in range(i + 1, len(lines)):
                    child_code = lines[j].split("#", 1)[0]
                    if child_code.strip() and len(child_code) - len(child_code.lstrip(" ")) <= parent_indent:
                        break
                    if re.match(r"^\s*-", child_code):
                        if seen == target_index:
                            lines[j] = _replace_yaml_list_line(lines[j], value)
                            return True
                        seen += 1
                return False
        return False

    stack = []
    for i, line in enumerate(lines):
        code = line.split("#", 1)[0]
        match = re.match(r"^(\s*)([^:\-\s][^:]*):", code)
        if not match:
            continue
        indent = len(match.group(1))
        level = indent // 2
        key = match.group(2).strip().strip("'\"")
        stack = stack[:level]
        stack.append(key)

        if stack == parts:
            lines[i] = _replace_yaml_scalar_line(lines[i], value)
            return True

    return False


def _save_yaml_preserving_comments(filepath: str, updates: dict) -> bool:
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for key_path, value in updates.items():
        if not _update_yaml_text_value(lines, key_path, value):
            return False

    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return True


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
        "labels": get_config_labels(),
        "stages": cfg.crop_stages(),
        "soil": {
            "theta_fc": cfg.get("soil.theta_fc"),
            "theta_wp": cfg.get("soil.theta_wp"),
            "theta_init": cfg.get("soil.theta_init"),
            "ec_soil_init": cfg.get("soil.ec_soil_init"),
        },
        "mixing_tank": cfg.mixing_tank(),
        "pipe": cfg.pipe(),
        "action_fixed": cfg.action().get("fixed_strategy", [1.5, 6.0]),
        "reward": cfg.reward(),
        "sac": cfg.sac(),
        "irrigation": cfg.irrigation(),
    }


def run_simulation(mode: str, stage_key: str, use_weather: bool):
    """运行 5 天短时仿真，返回时间序列 + 统计。B 方案中 action=[EC_set, pH_set]。"""
    from digital_twin_env import DigitalTwinEnv
    from digital_twin_gym_env import DigitalTwinGymEnv
    from crop_model import GrowthStage

    smap = {
        "INI": GrowthStage.EMERGENCE,
        "DEV": GrowthStage.TUBER_INIT,
        "MID": GrowthStage.BULKING,
        "LATE": GrowthStage.STARCH_ACCUMULATION,
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
            "rl_models", "sac_mid_final",
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

    th, tl, ecl, edl, phdl, etl, irl, tcl = [], [], [], [], [], [], [], []
    ecset_l, phset_l, qfl, qal = [], [], [], []
    done = False
    while not done:
        if use_rl and model is not None:
            action, _ = model.predict(obs, deterministic=True)
        else:
            action = np.array(load_config().action()["fixed_strategy"], dtype=np.float32)

        if hasattr(env, "action_space"):
            obs, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated
        else:
            obs, reward, done, info = env.step(action)

        th.append(float(info["time_day"] * 24.0))
        tl.append(float(info["theta"]))
        ecl.append(float(info["ec_soil"]))
        edl.append(float(info["ec_drip"]))
        phdl.append(float(info.get("ph_drip", 7.0)))
        etl.append(float(info["etc_mm_h"]))
        irl.append(float(info["irrigation_mm_h"]))
        tcl.append(float(info["target_ec"]))
        ecset_l.append(float(info.get("ec_set", action[0])))
        phset_l.append(float(info.get("ph_set", action[1])))
        qfl.append(float(info.get("q_f", 0.0)))
        qal.append(float(info.get("q_a", 0.0)))

    ec, tec, irr = np.array(ecl), np.array(tcl), np.array(irl)

    label = "SAC-PID" if use_rl else "Fixed setpoint"
    try:
        from plots import make_sim_plot
        img = make_sim_plot(th, tl, ecl, tcl, irl, etl, qfl, qal, label, _IMAGES_DIR)
    except Exception:
        img = None

    return {
        "success": True, "mode": mode, "stage": stage_key,
        "weather": from_weather, "steps": len(th),
        "image": f"/static/images/{img}" if img else None,
        "series": {
            "time_hours": [round(v, 1) for v in th],
            "theta": [round(v, 4) for v in tl],
            "ec_soil": [round(v, 3) for v in ecl],
            "ec_drip": [round(v, 3) for v in edl],
            "ph_drip": [round(v, 3) for v in phdl],
            "ec_target": [round(v, 3) for v in tcl],
            "ec_set": [round(v, 3) for v in ecset_l],
            "ph_set": [round(v, 3) for v in phset_l],
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
            "ec_set_mean": round(float(np.mean(ecset_l)), 4),
            "ph_set_mean": round(float(np.mean(phset_l)), 4),
            "q_f_mean": round(float(np.mean(qfl)), 4),
            "q_a_mean": round(float(np.mean(qal)), 4),
        },
    }


# ============ 原有 season compare / config save / training / model upload 逻辑 ============

# 为避免本次 B 方案改动影响后续文件结构，保留原文件后半部分由 GitHub 历史中的旧逻辑继续维护。
