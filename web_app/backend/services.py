"""业务逻辑层 — 仿真、季节对比、天气、配置、训练管理。"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from config_loader import load_config, reload_config
from sac_model_registry import get_stage_model_path

STAGE_MAP = {"ini": "INI", "dev": "DEV", "mid": "MID", "late": "LATE"}

training_lock = threading.Lock()
upload_lock = threading.Lock()
calibration_lock = threading.Lock()

_IMAGES_DIR = os.path.join(os.path.dirname(__file__), "static", "images")
os.makedirs(_IMAGES_DIR, exist_ok=True)

_SECTION_FILE_MAP = {
    "crop": "crop.yaml",
    "irrigation": "irrigation.yaml",
    "reward": "reward.yaml",
    "sac": "training.yaml",
}
_SIMULATION_KEYS = {"env", "soil", "mixing_tank", "pipe", "action", "obs", "day_night", "plc", "experiment"}

_training_state = {
    "running": False,
    "pid": None,
    "stage": None,
    "timesteps": 0,
    "target_steps": 0,
    "start_time": None,
    "progress": 0,
    "log_lines": [],
    "error": None,
}
_training_process: subprocess.Popen | None = None
_upload_progress = {"done": True, "total": 0, "uploaded": 0, "skipped": 0, "current": "", "errors": [], "processed": 0}


def _get_project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _get_config_dir() -> str:
    return os.path.join(_get_project_root(), "config")


def _get_rl_models_dir() -> str:
    return os.path.join(_get_project_root(), "rl_models")


def _get_rl_logs_dir() -> str:
    path = os.path.join(_get_project_root(), "rl_logs")
    os.makedirs(path, exist_ok=True)
    return path


def _extract_yaml_inline_comments(filepath: str) -> dict:
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


def get_config_labels() -> dict:
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
                seen = 0
                for j in range(i + 1, len(lines)):
                    child_code = lines[j].split("#", 1)[0]
                    if child_code.strip() and len(child_code) - len(child_code.lstrip(" ")) <= indent:
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
    if not use_weather:
        env_cfg = load_config().env()
        irr_cfg = load_config().irrigation()
        return env_cfg.get("et0_mm_day", 5.0), irr_cfg.get("rain_mm_day", 2.0), False
    try:
        from weather_client import get_et0_rain
        et0, rain = get_et0_rain()
        return et0, rain, True
    except Exception:
        env_cfg = load_config().env()
        irr_cfg = load_config().irrigation()
        return env_cfg.get("et0_mm_day", 5.0), irr_cfg.get("rain_mm_day", 2.0), False


def get_config_data():
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
        "action_fixed": cfg.action().get("fixed_strategy", [1.0, 0.0]),
        "reward": cfg.reward(),
        "sac": cfg.sac(),
        "irrigation": cfg.irrigation(),
        "plc": cfg.plc(),
    }


def run_simulation(mode: str, stage_key: str, use_weather: bool):
    """运行 5 天短时仿真。V2 中 action=[water_multiplier, EC_residual]。"""
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
        env = DigitalTwinGymEnv(growth_stage="MID", area_ha=0.1, dt_min=60.0, ep_len_days=5.0, et0_mm_day=et0_val)
        obs, _ = env.reset()
        from stable_baselines3 import SAC
        mp = str(get_stage_model_path(stage_key))
        if os.path.exists(mp + ".zip"):
            model = SAC.load(mp)
        else:
            use_rl = False
            env = DigitalTwinEnv(growth_stage=stage, area_ha=0.1, dt_min=60.0, ep_len_days=5.0, et0_mm_day=et0_val)
            obs = env.reset()
    else:
        env = DigitalTwinEnv(growth_stage=stage, area_ha=0.1, dt_min=60.0, ep_len_days=5.0, et0_mm_day=et0_val)
        obs = env.reset()

    th, tl, ecl, edl, phdl, etl, irl, tcl = [], [], [], [], [], [], [], []
    ecset_l, phset_l, qfl, qal = [], [], [], []
    done = False
    while not done:
        if use_rl and model is not None:
            action, _ = model.predict(obs, deterministic=True)
        else:
            action = np.array(load_config().action().get("fixed_strategy", [1.0, 0.0]), dtype=np.float32)

        if hasattr(env, "action_space"):
            obs, _reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated
        else:
            obs, _reward, done, info = env.step(action)

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
        "success": True,
        "mode": mode,
        "stage": stage_key,
        "weather": from_weather,
        "steps": len(th),
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


def run_season_compare(use_weather: bool):
    from digital_twin_env import DigitalTwinEnv
    from irrigation_schedule import run_season_simulation, get_irrigation_schedule

    et0_val, rain_val, from_weather = get_weather_data(use_weather)
    schedule = get_irrigation_schedule()
    results = {}
    for strategy in ["T1", "T2"]:
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
            initial_theta=env.soil.theta_fc,
            initial_ec=0.1,
            verbose=False,
        )
        results[strategy] = res

    def _r(a, n=4):
        return [round(float(v), n) for v in a]

    t1, t2 = results["T1"], results["T2"]
    em1 = float(np.abs(t1["ec_soil"] - t1["target_ec"]).mean())
    em2 = float(np.abs(t2["ec_soil"] - t2["target_ec"]).mean())
    rain_total_mm = float(rain_val) * 90.0
    wue1 = float(t1["total_etc_mm"]) / (float(t1["total_scheduled_irrigation_mm"]) + rain_total_mm + 1e-6)
    wue2 = float(t2["total_etc_mm"]) / (float(t2["total_scheduled_irrigation_mm"]) + rain_total_mm + 1e-6)
    t1e = t1["theta"][t1["event_marker"] > 0.5]
    t2e = t2["theta"][t2["event_marker"] > 0.5]
    cv1 = float(t1e.std() / (t1e.mean() + 1e-6)) if len(t1e) > 0 else 0
    cv2 = float(t2e.std() / (t2e.mean() + 1e-6)) if len(t2e) > 0 else 0

    try:
        from plots import make_season_plot
        img = make_season_plot(t1, t2, _IMAGES_DIR)
    except Exception:
        img = None

    return {
        "success": True,
        "weather": from_weather,
        "image": f"/static/images/{img}" if img else None,
        "T1": {k: _r(t1[k]) for k in ["time_day", "theta", "ec_soil", "target_ec", "irrigation_mm_h", "etc_mm_h", "event_marker"]},
        "T2": {k: _r(t2[k]) for k in ["time_day", "theta", "ec_soil", "target_ec", "irrigation_mm_h", "etc_mm_h", "event_marker"]},
        "stats": {
            "ec_mae_t1": round(em1, 3),
            "ec_mae_t2": round(em2, 3),
            "theta_mean_t1": round(float(t1["theta"].mean()), 4),
            "theta_mean_t2": round(float(t2["theta"].mean()), 4),
            "total_irr_t1": round(float(t1["total_scheduled_irrigation_mm"]), 1),
            "total_irr_t2": round(float(t2["total_scheduled_irrigation_mm"]), 1),
            "simulated_irr_t1": round(float(t1["total_simulated_irrigation_mm"]), 1),
            "simulated_irr_t2": round(float(t2["total_simulated_irrigation_mm"]), 1),
            "total_et_t1": round(float(t1["total_etc_mm"]), 1),
            "total_et_t2": round(float(t2["total_etc_mm"]), 1),
            "theta_cv_t1": round(cv1, 4),
            "theta_cv_t2": round(cv2, 4),
            "wue_t1": round(wue1, 4),
            "wue_t2": round(wue2, 4),
            "wue_change_pct": round((wue2 - wue1) / (wue1 + 1e-6) * 100, 1),
        },
    }


def save_config_section(section: str, updates: dict):
    config_dir = _get_config_dir()
    filename = "simulation.yaml" if section == "simulation" else _SECTION_FILE_MAP.get(section)
    if not filename:
        raise ValueError(f"未知配置段: {section}")
    filepath = os.path.join(config_dir, filename)
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"配置文件不存在: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    normalized_updates = {}
    for key_path, value in updates.items():
        if section == "crop" and key_path.startswith("stages."):
            key_path = "crop." + key_path
        parts = key_path.split(".")
        node = data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
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
        normalized_updates[key_path] = value

    if not _save_yaml_preserving_comments(filepath, normalized_updates):
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    reload_config()
    return {"success": True, "section": section}



def get_active_calibration() -> dict:
    """Return the active calibration metadata and selected soil parameters."""
    cfg = reload_config()
    calibration = dict(cfg.calibration())
    soil = cfg.soil_v2()
    return {
        "success": True,
        "active": bool(calibration),
        "calibration": calibration,
        "soil_model": soil.get("default_model", "lumped_v1"),
        "parameter_status": soil.get("parameter_status", "unknown"),
        "parameter_version": soil.get("parameter_version", "unknown"),
        "domain_randomization": soil.get("domain_randomization", {}),
    }


def run_field_calibration(file_bytes: bytes, filename: str, trials: int = 300,
                          validation_fraction: float = 0.20, activate: bool = True) -> dict:
    """Run field calibration from an uploaded CSV and optionally activate it."""
    if not file_bytes:
        raise ValueError("Uploaded CSV is empty")
    if len(file_bytes) > 50 * 1024 * 1024:
        raise ValueError("CSV exceeds the 50 MB limit")
    trials = max(10, min(int(trials), 5000))
    validation_fraction = float(validation_fraction)
    if not 0.05 <= validation_fraction <= 0.50:
        raise ValueError("validation_fraction must be between 0.05 and 0.50")

    with calibration_lock:
        if _training_state["running"]:
            raise RuntimeError("Stop SAC training before activating a new calibration profile")
        root = Path(_get_project_root())
        calibration_dir = root / "config" / "calibration"
        upload_dir = calibration_dir / "uploads"
        run_dir = calibration_dir / "runs"
        upload_dir.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir(parents=True, exist_ok=True)
        safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(filename or "field.csv").stem)[:80] or "field"
        stamp = time.strftime("%Y%m%d-%H%M%S")
        digest = __import__("hashlib").sha256(file_bytes).hexdigest()[:8]
        csv_path = upload_dir / f"{stamp}-{safe_stem}-{digest}.csv"
        output_path = run_dir / f"{stamp}-{safe_stem}-{digest}.yaml"
        csv_path.write_bytes(file_bytes)

        cmd = [
            sys.executable, str(root / "scripts" / "calibrate_field_model.py"),
            str(csv_path), "--trials", str(trials),
            "--validation-fraction", str(validation_fraction),
            "--output", str(output_path),
        ]
        if activate:
            cmd.append("--activate")
        result = subprocess.run(
            cmd, cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=3600,
        )
        if result.returncode != 0:
            details = (result.stderr or result.stdout or "calibration failed").strip()
            raise RuntimeError(details[-4000:])
        profile = yaml.safe_load(output_path.read_text(encoding="utf-8")) or {}
        if activate:
            reload_config()
        return {
            "success": True,
            "activated": bool(activate),
            "profile_path": str(output_path),
            "report_path": str(output_path.with_suffix(".report.json")),
            "calibration": profile.get("calibration", {}),
            "stdout": result.stdout[-4000:],
        }


def get_training_status():
    global _training_process
    with training_lock:
        if _training_state["running"] and _training_process is not None:
            ret = _training_process.poll()
            if ret is not None:
                _training_state["running"] = False
                _training_state["pid"] = None
                if ret != 0:
                    _training_state["error"] = f"训练进程退出码: {ret}"
        return dict(_training_state)


def start_training(stage: str, timesteps: int, resume: bool = False,
                   load_model: str | None = None, soil_model: str = "layered_v2",
                   domain_randomization: bool = True):
    global _training_process
    with training_lock:
        if _training_state["running"]:
            return {"success": False, "error": "训练已经在运行"}
        stage = (stage or "MID").upper()
        timesteps = int(timesteps or load_config().sac().get("total_timesteps", 120000))
        soil_model = soil_model if soil_model in {"lumped_v1", "layered_v2"} else "layered_v2"
        cmd = [
            sys.executable, os.path.join(_get_project_root(), "train_sac.py"),
            "--stage", stage, "--timesteps", str(timesteps),
            "--soil-model", soil_model,
        ]
        if load_model:
            cmd.extend(["--load-path", load_model])
        elif resume:
            cmd.append("--resume")
        else:
            cmd.append("--fresh")
        if soil_model == "layered_v2" and not domain_randomization:
            cmd.append("--disable-domain-randomization")
        os.makedirs(_get_rl_logs_dir(), exist_ok=True)
        log_path = os.path.join(_get_rl_logs_dir(), "web_training.log")
        log_f = open(log_path, "a", encoding="utf-8")
        _training_process = subprocess.Popen(cmd, cwd=_get_project_root(), stdout=log_f, stderr=subprocess.STDOUT)
        _training_state.update({
            "running": True,
            "pid": _training_process.pid,
            "stage": stage,
            "soil_model": soil_model,
            "calibration_id": load_config().calibration().get("id"),
            "timesteps": 0,
            "target_steps": timesteps,
            "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "progress": 0,
            "log_lines": [f"启动训练: {' '.join(cmd)}"],
            "error": None,
        })
        return {"success": True, "pid": _training_process.pid, "cmd": cmd}


def stop_training():
    global _training_process
    with training_lock:
        if not _training_state["running"] or _training_process is None:
            return {"success": True, "message": "当前没有训练任务"}
        try:
            if os.name == "nt":
                _training_process.terminate()
            else:
                os.kill(_training_process.pid, signal.SIGTERM)
        except Exception as e:
            return {"success": False, "error": str(e)}
        _training_state["running"] = False
        _training_state["pid"] = None
        return {"success": True, "message": "已请求停止训练"}


def _parse_model_name(fname: str) -> dict | None:
    if not fname.endswith(".zip"):
        return None
    name = fname[:-4]
    m = re.match(r"sac_(ini|dev|mid|late)_(\d+)_steps", name)
    if m:
        return {"name": name, "stage": m.group(1).upper(), "steps": f"{int(m.group(2)):,} 步", "steps_num": int(m.group(2))}
    m = re.match(r"sac_(ini|dev|mid|late)_final", name)
    if m:
        return {"name": name, "stage": m.group(1).upper(), "steps": "最终版", "steps_num": 999999}
    if fname == "best_model.zip":
        return {"name": name, "stage": "BEST", "steps": "best", "steps_num": 0}
    return None


def get_model_info(query_cloud: bool = False):
    if query_cloud:
        try:
            from cloud_storage import query_all_models
            return query_all_models()
        except Exception as e:
            return {"models": [], "error": str(e)}
    models_dir = _get_rl_models_dir()
    os.makedirs(models_dir, exist_ok=True)
    models = []
    for dirpath, _dirnames, filenames in os.walk(models_dir):
        for fname in sorted(filenames):
            meta = _parse_model_name(fname)
            if not meta:
                continue
            path = os.path.join(dirpath, fname)
            st = os.stat(path)
            meta.update({
                "size_mb": round(st.st_size / (1024 * 1024), 2),
                "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                "relative_path": os.path.relpath(path, models_dir).replace(os.sep, "/"),
            })
            models.append(meta)
    return {"models": models, "models_dir": models_dir}


def delete_model(name: str):
    safe = os.path.basename(name).replace(".zip", "")
    path = os.path.join(_get_rl_models_dir(), safe + ".zip")
    if not os.path.exists(path):
        return {"success": False, "error": "模型不存在"}
    os.remove(path)
    return {"success": True, "name": safe}


def upload_models_to_cloud():
    try:
        from cloud_storage import upload_all_models
        with upload_lock:
            _upload_progress.update({"done": False, "total": 0, "uploaded": 0, "skipped": 0, "current": "", "errors": [], "processed": 0})
            threading.Thread(target=upload_all_models, args=(_get_rl_models_dir(), False, _upload_progress), daemon=True).start()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def upload_selected_models(names: list[str]):
    try:
        from cloud_storage import upload_model, ensure_database
        ensure_database()
        results = []
        for name in names:
            safe = os.path.basename(name).replace(".zip", "")
            path = os.path.join(_get_rl_models_dir(), safe + ".zip")
            if not os.path.exists(path):
                results.append({"name": safe, "error": "文件不存在"})
                continue
            meta = _parse_model_name(safe + ".zip") or {"stage": "", "steps": "", "steps_num": 0}
            st = os.stat(path)
            with open(path, "rb") as f:
                file_data = f.read()
            res = upload_model(safe, meta.get("stage", ""), meta.get("steps", ""), meta.get("steps_num", 0), round(st.st_size / (1024 * 1024), 2), time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)), file_data)
            results.append({"name": safe, **res})
        return {"success": True, "results": results}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_upload_progress():
    return dict(_upload_progress)


def stop_upload():
    _upload_progress["_cancel"] = True
    return {"success": True}


def clear_training_progress():
    with training_lock:
        _training_state.update({"progress": 0, "log_lines": [], "error": None})
    progress_path = os.path.join(_get_rl_logs_dir(), "training_progress.json")
    if os.path.exists(progress_path):
        try:
            os.remove(progress_path)
        except Exception:
            pass
    return {"success": True}

