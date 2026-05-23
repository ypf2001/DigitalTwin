"""请求/响应数据模型"""
from pydantic import BaseModel


class SimulateRequest(BaseModel):
    mode: str = "fixed"
    weather: bool = False
    stage: str = "BULKING"


class SeasonRequest(BaseModel):
    weather: bool = False
