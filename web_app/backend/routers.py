"""路由 / 控制器层 — 对接 FastAPI 路由装饰器"""

import traceback

from fastapi import APIRouter

from models import SimulateRequest, SeasonRequest
from services import (
    get_weather_data, get_config_data, run_simulation, run_season_compare,
)

router = APIRouter()


@router.get("/api/weather")
def api_weather():
    try:
        et0, rain, _ = get_weather_data(use_weather=True)
        return {"success": True, "et0_mm_day": round(float(et0), 2),
                "rain_mm_day": round(float(rain), 2)}
    except Exception as e:
        et0, rain, _ = get_weather_data(use_weather=False)
        return {"success": False, "et0_mm_day": et0, "rain_mm_day": rain,
                "error": str(e)}


@router.get("/api/config")
def api_config():
    try:
        return get_config_data()
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/simulate")
def simulate(req: SimulateRequest):
    try:
        return run_simulation(req.mode, req.stage, req.weather)
    except Exception as e:
        return {"success": False, "error": str(e),
                "traceback": traceback.format_exc()}


@router.post("/api/season-compare")
def season_compare(req: SeasonRequest):
    try:
        return run_season_compare(req.weather)
    except Exception as e:
        return {"success": False, "error": str(e),
                "traceback": traceback.format_exc()}
