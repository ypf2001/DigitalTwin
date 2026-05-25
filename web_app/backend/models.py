"""请求/响应数据模型"""
from typing import Dict, List
from pydantic import BaseModel, Field, validator


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
    stage: str = Field(default="MID")
    timesteps: int = Field(default=120000, ge=1000, le=1000000)
    resume: bool = False
    load_model: str = ""

    @validator('stage')
    def validate_stage(cls, v):
        if v not in ["INI", "DEV", "MID", "LATE"]:
            raise ValueError('stage must be one of: INI, DEV, MID, LATE')
        return v


class UploadSelectedRequest(BaseModel):
    names: List[str] = Field(default_factory=list)
