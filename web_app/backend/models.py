"""请求/响应数据模型"""
from typing import Dict

from pydantic import BaseModel


class SimulateRequest(BaseModel):
    mode: str = "fixed"
    weather: bool = False
    stage: str = "BULKING"


class SeasonRequest(BaseModel):
    weather: bool = False


class ConfigSaveRequest(BaseModel):
    section: str
    updates: Dict[str, object]


class TrainRequest(BaseModel):
    stage: str = "BULKING"
    timesteps: int = 120000
    resume: bool = False
