"""路由 / 控制器层 — 对接 FastAPI 路由装饰器"""

import traceback

from fastapi import APIRouter

from models import SimulateRequest, SeasonRequest, ConfigSaveRequest, TrainRequest
from services import (
    get_weather_data, get_config_data, run_simulation, run_season_compare,
    save_config_section, get_training_status, start_training, stop_training,
    get_model_info, upload_models_to_cloud, get_upload_progress,
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


@router.put("/api/config/save")
def save_config(req: ConfigSaveRequest):
    try:
        return save_config_section(req.section, req.updates)
    except Exception as e:
        return {"success": False, "error": str(e),
                "traceback": traceback.format_exc()}


# ============ 训练相关 API ============

@router.get("/api/training/status")
def training_status():
    """获取训练状态"""
    try:
        return get_training_status()
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/training/start")
def training_start(req: TrainRequest):
    """启动训练"""
    try:
        return start_training(req.stage, req.timesteps, req.resume, req.load_model)
    except Exception as e:
        return {"success": False, "error": str(e),
                "traceback": traceback.format_exc()}


@router.post("/api/training/stop")
def training_stop():
    """停止训练"""
    try:
        return stop_training()
    except Exception as e:
        return {"success": False, "error": str(e),
                "traceback": traceback.format_exc()}


@router.get("/api/training/models")
def training_models():
    """获取已有模型列表"""
    try:
        return get_model_info()
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/training/upload")
def upload_models():
    """上传本地所有模型到云端 MySQL"""
    try:
        result = upload_models_to_cloud()
        return result
    except Exception as e:
        return {"success": False, "error": str(e),
                "traceback": traceback.format_exc()}


@router.get("/api/training/upload/progress")
def upload_progress():
    """查询上传进度"""
    try:
        return get_upload_progress()
    except Exception as e:
        return {"error": str(e)}
