"""
马铃薯施肥灌溉数字孪生系统 — FastAPI 后端
==========================================
前后端分离：提供 REST API，供 Vue 前端调用。
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import matplotlib
matplotlib.use('Agg')

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import numpy as np

from config_loader import load_config

app = FastAPI(title="数字孪生 API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class SimulateRequest(BaseModel):
    mode: str = "fixed"
    weather: bool = False
    stage: str = "BULKING"


class SeasonRequest(BaseModel):
    weather: bool = False


def _get_weather(use_weather: bool):
    if not use_weather:
        env_cfg = load_config().env(); irr_cfg = load_config().irrigation()
        return env_cfg["et0_mm_day"], irr_cfg.get("rain_mm_day", 2.0), False
    try:
        from weather_client import get_et0_rain
        et0, rain = get_et0_rain()
        return et0, rain, True
    except Exception:
        env_cfg = load_config().env(); irr_cfg = load_config().irrigation()
        return env_cfg["et0_mm_day"], irr_cfg.get("rain_mm_day", 2.0), False


@app.get("/api/weather")
def api_weather():
    try:
        from weather_client import get_et0_rain
        et0, rain = get_et0_rain()
        return {"success": True, "et0_mm_day": round(float(et0), 2), "rain_mm_day": round(float(rain), 2)}
    except Exception as e:
        env_cfg = load_config().env(); irr_cfg = load_config().irrigation()
        return {"success": False, "et0_mm_day": env_cfg["et0_mm_day"],
                "rain_mm_day": irr_cfg.get("rain_mm_day", 2.0), "error": str(e)}


@app.get("/api/config")
def api_config():
    try:
        env_cfg = load_config().env(); sim_cfg = load_config().simulation()
        act_cfg = load_config().action(); rew_cfg = load_config().reward()
        trn_cfg = load_config().training(); irr_cfg = load_config().irrigation()
        crop_cfg = load_config().crop_stages()
        return {
            "stages": crop_cfg,
            "soil": {"theta_fc": env_cfg.get("theta_fc"), "theta_wp": env_cfg.get("theta_wp"),
                     "theta_init": env_cfg.get("theta_init"), "ec_init": env_cfg.get("ec_init")},
            "tank": sim_cfg.get("tank", {}), "pipe": sim_cfg.get("pipe", {}),
            "action_fixed": act_cfg.get("fixed_strategy", [5.0, 1.0]),
            "reward": rew_cfg, "training": trn_cfg, "irrigation": irr_cfg,
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/simulate")
def run_simulation(req: SimulateRequest):
    try:
        from digital_twin_env import DigitalTwinEnv
        from digital_twin_gym_env import DigitalTwinGymEnv
        from crop_model import GrowthStage

        smap = {"EMERGENCE": GrowthStage.EMERGENCE, "VEGETATIVE": GrowthStage.VEGETATIVE,
                "TUBER_INIT": GrowthStage.TUBER_INIT, "BULKING": GrowthStage.BULKING,
                "STARCH_ACCUMULATION": GrowthStage.STARCH_ACCUMULATION, "MATURATION": GrowthStage.MATURATION}
        stage = smap.get(req.stage, GrowthStage.BULKING)
        et0_val, _, from_weather = _get_weather(req.weather)

        use_rl = (req.mode == "sac")
        model = None
        if use_rl:
            env = DigitalTwinGymEnv(growth_stage="MID", area_ha=0.1, dt_min=60.0,
                                    ep_len_days=5.0, et0_mm_day=et0_val)
            obs, _ = env.reset()
            from stable_baselines3 import SAC
            mp = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                              'rl_models', 'sac_mid_final')
            if os.path.exists(mp + ".zip"):
                model = SAC.load(mp)
            else:
                use_rl = False
        else:
            env = DigitalTwinEnv(growth_stage=stage, area_ha=0.1, dt_min=60.0,
                                 ep_len_days=5.0, et0_mm_day=et0_val)
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
            tl.append(float(info['theta'])); ecl.append(float(info['ec_soil']))
            edl.append(float(info['ec_drip'])); etl.append(float(info['etc_mm_h']))
            irl.append(float(info['irrigation_mm_h'])); tcl.append(float(info['target_ec']))
            qfl.append(float(action[0])); qal.append(float(action[1]))

        ec, tec, irr = np.array(ecl), np.array(tcl), np.array(irl)
        return {"success": True, "mode": req.mode, "stage": req.stage, "weather": from_weather,
                "steps": len(th),
                "series": {"time_hours": [round(v, 1) for v in th],
                           "theta": [round(v, 4) for v in tl],
                           "ec_soil": [round(v, 3) for v in ecl],
                           "ec_drip": [round(v, 3) for v in edl],
                           "ec_target": [round(v, 3) for v in tcl],
                           "etc_mm_h": [round(v, 4) for v in etl],
                           "irrigation_mm_h": [round(v, 4) for v in irl],
                           "q_f": [round(v, 4) for v in qfl],
                           "q_a": [round(v, 4) for v in qal]},
                "stats": {"theta_mean": round(float(np.mean(tl)), 4),
                          "theta_final": round(float(tl[-1]), 4),
                          "ec_soil_final": round(float(ecl[-1]), 3),
                          "ec_mae": round(float(np.abs(ec - tec).mean()), 3),
                          "total_irrigation_mm": round(float(irr.sum()), 2),
                          "total_et_mm": round(float(np.sum(etl)), 2),
                          "q_f_mean": round(float(np.mean(qfl)), 4),
                          "q_a_mean": round(float(np.mean(qal)), 4)}}
    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@app.post("/api/season-compare")
def season_compare(req: SeasonRequest):
    try:
        from digital_twin_env import DigitalTwinEnv
        from irrigation_schedule import run_season_simulation, get_irrigation_schedule

        et0_val, rain_val, from_weather = _get_weather(req.weather)
        schedule = get_irrigation_schedule()
        results = {}
        for strategy in ["T1", "T2"]:
            env = DigitalTwinEnv(growth_stage=schedule[0].growth_stage, area_ha=0.1,
                                 dt_min=15.0, ep_len_days=90.0, et0_mm_day=et0_val, seed=42)
            res = run_season_simulation(env, model=None, strategy=strategy, area_ha=0.1,
                                        dt_min=15.0, rain_mm_day=rain_val,
                                        initial_theta=env.soil.theta_fc, initial_ec=0.1, verbose=False)
            results[strategy] = res

        def _r(a, n=4): return [round(float(v), n) for v in a]
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

        return {"success": True, "weather": from_weather,
                "T1": {k: _r(t1[k]) for k in ["time_day", "theta", "ec_soil", "ec_target",
                                                "irrigation_mm_h", "etc_mm_h", "event_marker"]},
                "T2": {k: _r(t2[k]) for k in ["time_day", "theta", "ec_soil", "ec_target",
                                                "irrigation_mm_h", "etc_mm_h", "event_marker"]},
                "stats": {"ec_mae_t1": round(em1, 3), "ec_mae_t2": round(em2, 3),
                          "theta_mean_t1": round(float(t1["theta"].mean()), 4),
                          "theta_mean_t2": round(float(t2["theta"].mean()), 4),
                          "theta_improve_pct": round((float(t2["theta"].mean()) - float(t1["theta"].mean())) / (float(t1["theta"].mean()) + 1e-6) * 100, 1),
                          "total_irr_t1": round(float(t1["total_irrigation_mm"]), 1),
                          "total_irr_t2": round(float(t2["total_irrigation_mm"]), 1),
                          "total_et_t1": round(float(t1["total_etc_mm"]), 1),
                          "total_et_t2": round(float(t2["total_etc_mm"]), 1),
                          "deep_drain_t1": round(dr1, 1), "deep_drain_t2": round(dr2, 1),
                          "theta_cv_t1": round(cv1, 4), "theta_cv_t2": round(cv2, 4),
                          "wue_t1": round(wue1, 4), "wue_t2": round(wue2, 4),
                          "wue_change_pct": round((wue2 - wue1) / (wue1 + 1e-6) * 100, 1)}}
    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


if __name__ == '__main__':
    import uvicorn
    print("\n" + "=" * 50)
    print("  数字孪生 API 服务")
    print("  http://localhost:5000")
    print("=" * 50 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=5000)
