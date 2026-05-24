"""业务逻辑层 — 仿真、季节对比、天气、配置"""

import os
import sys
import traceback

import numpy as np
import yaml

from config_loader import load_config, reload_config

_IMAGES_DIR = os.path.join(os.path.dirname(__file__), "static", "images")

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

    # 生成 matplotlib PNG 图
    label = "SAC" if use_rl else "Fixed"
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

    try:
        from plots import make_season_plot
        img = make_season_plot(t1, t2, _IMAGES_DIR)
    except Exception:
        img = None

    return {
        "success": True, "weather": from_weather,
        "image": f"/static/images/{img}" if img else None,
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


# ============ 训练相关 ============

import threading
import time
import json
import subprocess
import signal

# 全局训练状态
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


def _get_project_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _get_rl_models_dir():
    return os.path.join(_get_project_root(), "rl_models")


def _get_training_log_path():
    return os.path.join(_get_project_root(), "rl_logs", "training_progress.json")


def get_training_status():
    """获取训练状态"""
    global _training_state

    # 检查子进程是否还在运行
    if _training_state["running"] and _training_state["pid"]:
        try:
            if os.name == "nt":
                # 检查进程是否还在（不杀死它）
                result = subprocess.run(f"tasklist /FI \"PID eq {_training_state['pid']}\"",
                                      shell=True, capture_output=True, text=True)
                if str(_training_state["pid"]) not in result.stdout:
                    _training_state["running"] = False
                    _training_state["pid"] = None
            else:
                os.kill(_training_state["pid"], 0)
        except (ProcessLookupError, PermissionError):
            _training_state["running"] = False
            _training_state["pid"] = None

    # 从 train_output.log 读取最新进度
    import locale
    default_encoding = locale.getpreferredencoding(False) or 'utf-8'
    log_file = os.path.join(_get_project_root(), "rl_logs", "train_output.log")
    if os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding=default_encoding, errors='replace') as f:
                content = f.read()
            # 查找最新的 total_timesteps
            import re
            matches = re.findall(r'total_timesteps\s+\|\s+(\d+)', content)
            if matches:
                _training_state["timesteps"] = int(matches[-1])
        except Exception:
            pass

    # 计算进度百分比
    target = _training_state["target_steps"] if _training_state["target_steps"] > 0 else 120000
    if target > 0:
        _training_state["progress"] = min(100, _training_state["timesteps"] / target * 100)

    return {
        "running": _training_state["running"],
        "stage": _training_state["stage"],
        "timesteps": _training_state["timesteps"],
        "target_steps": _training_state["target_steps"] if _training_state["target_steps"] > 0 else 120000,
        "progress": round(_training_state["progress"], 1),
        "start_time": _training_state["start_time"],
        "log_lines": _training_state["log_lines"][-50:] if _training_state["log_lines"] else [],
        "error": _training_state["error"],
    }


def _training_worker(stage, timesteps, resume):
    """后台训练线程"""
    global _training_state

    try:
        project_root = _get_project_root()
        log_file = os.path.join(project_root, "rl_logs", "train_output.log")

        # 确保目录存在
        os.makedirs(os.path.join(project_root, "rl_models"), exist_ok=True)
        os.makedirs(os.path.join(project_root, "rl_logs"), exist_ok=True)

        # 构建命令 - 将输出重定向到文件
        cmd = [
            sys.executable,
            os.path.join(project_root, "train_sac.py"),
            "--stage", stage,
            "--timesteps", str(timesteps),
        ]
        if resume:
            cmd.append("--resume")

        # 启动训练进程，输出重定向到文件
        # 使用系统默认编码（Windows 中文系统通常是 GBK）
        import locale
        default_encoding = locale.getpreferredencoding(False) or 'utf-8'
        with open(log_file, "w", encoding=default_encoding, errors='replace') as f_out:
            process = subprocess.Popen(
                cmd,
                cwd=project_root,
                stdout=f_out,
                stderr=subprocess.STDOUT,
                text=True,
            )

        _training_state["pid"] = process.pid
        _training_state["running"] = True

        # 定期检查进程状态和读取日志
        import time
        last_pos = 0
        episode_rewards = []

        while True:
            # 检查进程是否结束
            ret = process.poll()
            if ret is not None:
                # 进程已结束，读取剩余日志
                with open(log_file, "r", encoding=default_encoding, errors='replace') as f:
                    f.seek(last_pos)
                    for line in f:
                        line = line.strip()
                        if line and ("episode" in line.lower() or "rew" in line.lower() or "step" in line.lower()):
                            episode_rewards.append(line[-100:] if len(line) > 100 else line)
                _training_state["log_lines"] = episode_rewards[-50:]
                _training_state["running"] = False
                _training_state["pid"] = None
                _training_state["target_steps"] = 0
                if ret != 0 and ret is not None:
                    _training_state["error"] = f"训练进程退出 (code: {ret})"
                break

            # 每秒读取一次日志
            time.sleep(1)
            try:
                with open(log_file, "r", encoding=default_encoding, errors='replace') as f:
                    f.seek(last_pos)
                    new_lines = f.readlines()
                    last_pos = f.tell()
                    for line in new_lines:
                        line = line.strip()
                        if line and ("episode" in line.lower() or "rew" in line.lower() or "step" in line.lower() or "timestep" in line.lower()):
                            episode_rewards.append(line[-100:] if len(line) > 100 else line)
                    if new_lines:
                        _training_state["log_lines"] = episode_rewards[-50:]
            except Exception:
                pass

    except Exception as e:
        _training_state["running"] = False
        _training_state["error"] = str(e)
        _training_state["target_steps"] = 0
        import traceback as tb
        tb.print_exc()


def start_training(stage: str, timesteps: int, resume: bool = False):
    """启动训练"""
    global _training_state

    if _training_state["running"]:
        return {"success": False, "error": "训练已在进行中"}

    # 检查模型文件
    stage_short_map = {
        "BULKING": "mid", "STARCH_ACCUMULATION": "late",
        "EMERGENCE": "ini", "VEGETATIVE": "dev",
        "TUBER_INIT": "dev", "MATURATION": "late",
    }
    model_short = stage_short_map.get(stage, "mid")
    model_path = os.path.join(_get_rl_models_dir(), f"sac_{model_short}_final.zip")
    model_exists = os.path.exists(model_path)

    # 检查是否有之前的训练进度
    log_file = os.path.join(_get_project_root(), "rl_logs", "train_output.log")
    last_timesteps = 0
    if os.path.exists(log_file):
        try:
            import locale
            default_encoding = locale.getpreferredencoding(False) or 'utf-8'
            with open(log_file, "r", encoding=default_encoding, errors='replace') as f:
                content = f.read()
            import re
            matches = re.findall(r'total_timesteps\s+\|\s+(\d+)', content)
            if matches:
                last_timesteps = int(matches[-1])
        except Exception:
            pass

    # resume=true 时续训，resume=false 时清空日志重新开始
    if not resume:
        # 清空日志文件，重新开始
        try:
            with open(log_file, "w", encoding="utf-8", errors='replace') as f:
                f.write("")
        except Exception:
            pass
        last_timesteps = 0

    auto_resume = resume

    # 重启时需要先重新加载配置
    reload_config()

    # 重置状态
    _training_state.update({
        "running": True,
        "stage": stage,
        "timesteps": last_timesteps,
        "target_steps": timesteps,
        "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "progress": last_timesteps / timesteps * 100 if timesteps > 0 else 0,
        "log_lines": [],
        "error": None,
    })

    # 启动后台线程
    thread = threading.Thread(target=_training_worker, args=(stage, timesteps, auto_resume))
    thread.daemon = True
    thread.start()

    msg = "继续训练" if auto_resume else "开始训练"
    return {
        "success": True,
        "message": f"{msg} {stage}，目标 {timesteps} 步（已训练 {last_timesteps} 步）",
        "stage": stage,
        "target_steps": timesteps,
        "resume_available": model_exists or (last_timesteps > 0),
        "last_timesteps": last_timesteps,
    }


def stop_training():
    """停止训练"""
    global _training_state

    if not _training_state["running"]:
        return {"success": False, "error": "没有正在运行的训练"}

    if _training_state["pid"]:
        try:
            if os.name == "nt":
                subprocess.run(f"taskkill /F /PID {_training_state['pid']}",
                             shell=True, capture_output=True)
            else:
                os.kill(_training_state["pid"], signal.SIGTERM)
        except Exception:
            pass

    _training_state["running"] = False
    _training_state["pid"] = None
    _training_state["target_steps"] = 0
    _training_state["error"] = "用户手动停止"

    return {"success": True, "message": "训练已停止"}


def get_model_info():
    """获取已有模型信息 — 扫描 rl_models 下所有 zip"""
    import re
    models = []
    models_dir = _get_rl_models_dir()

    stage_names = {
        "ini": "EMERGENCE (出苗期)",
        "dev": "VEGETATIVE/TUBER_INIT (营养/块茎形成)",
        "mid": "BULKING (块茎膨大期)",
        "late": "STARCH_ACCUMULATION/MATURATION (淀粉积累/成熟)",
    }

    if not os.path.isdir(models_dir):
        return {"models": [], "models_dir": models_dir}

    for fname in sorted(os.listdir(models_dir)):
        if not fname.endswith(".zip"):
            continue

        filepath = os.path.join(models_dir, fname)
        mtime = os.path.getmtime(filepath)
        size_mb = os.path.getsize(filepath) / (1024 * 1024)

        # 解析文件名: sac_{stage}_{steps}_steps.zip 或 sac_{stage}_final.zip 或 best_model.zip
        stage_short = None
        steps_label = ""

        m = re.match(r"sac_(ini|dev|mid|late)_(\d+)_steps\.zip", fname)
        if m:
            stage_short = m.group(1)
            steps = int(m.group(2))
            steps_label = f"{steps:,} 步"
        elif re.match(r"sac_(ini|dev|mid|late)_final\.zip", fname):
            m2 = re.match(r"sac_(ini|dev|mid|late)_final\.zip", fname)
            stage_short = m2.group(1)
            steps_label = "最终版"
        elif fname == "best_model.zip":
            stage_short = "mid"
            steps_label = "最佳模型"

        if stage_short is None:
            continue

        stage_name = stage_names.get(stage_short, stage_short)
        models.append({
            "name": fname.replace(".zip", ""),
            "stage": stage_name,
            "steps": steps_label,
            "size_mb": round(size_mb, 2),
            "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
        })

    models.sort(key=lambda x: x["mtime"], reverse=True)
    models = models[:10]
    return {"models": models, "models_dir": models_dir}

