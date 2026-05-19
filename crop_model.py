"""
作物模型模块 — CropModel
=========================
提供马铃薯 (Potato) 在不同生育期的作物系数 Kc 和目标土壤 EC。

生育期数据从 config.yaml 的 crop.stages 段读取。
"""

from enum import Enum
from config_loader import load_config


class GrowthStage(Enum):
    """马铃薯生育阶段枚举。"""
    EMERGENCE = "emergence"
    VEGETATIVE = "vegetative"
    TUBER_INIT = "tuber_init"
    BULKING = "bulking"
    STARCH_ACCUMULATION = "starch_accumulation"
    MATURATION = "maturation"


# 阶段名到 GrowthStage 的映射
_STAGE_KEY_MAP = {
    "emergence": GrowthStage.EMERGENCE,
    "vegetative": GrowthStage.VEGETATIVE,
    "tuber_init": GrowthStage.TUBER_INIT,
    "bulking": GrowthStage.BULKING,
    "starch_accumulation": GrowthStage.STARCH_ACCUMULATION,
    "maturation": GrowthStage.MATURATION,
}


def _build_tables():
    """从配置文件动态构建 Kc、target_EC、root_depth 三张表。"""
    stages_cfg = load_config().crop_stages()
    kc = {}
    ec = {}
    rd = {}
    for key, vals in stages_cfg.items():
        stage = _STAGE_KEY_MAP[key]
        kc[stage] = float(vals["kc"])
        ec[stage] = float(vals["target_ec"])
        rd[stage] = float(vals["root_depth"])
    return kc, ec, rd


KC_TABLE, TARGET_EC_TABLE, ROOT_DEPTH_TABLE = _build_tables()


class CropModel:
    """马铃薯作物模型，提供 Kc 和目标 EC 查询。

    用法
    ----
    >>> crop = CropModel(GrowthStage.BULKING)
    >>> etc = crop.get_etc(GrowthStage.BULKING, et0=5.0)   # 5 mm/day
    >>> target_ec = crop.get_target_ec(GrowthStage.BULKING)
    """

    def __init__(self, initial_stage: GrowthStage = GrowthStage.EMERGENCE):
        self.current_stage = initial_stage

    def get_kc(self, stage: GrowthStage) -> float:
        """返回指定生育期的作物系数 Kc。

        参数
        ----------
        stage : GrowthStage
            生育阶段

        返回
        ----------
        kc : float
            作物系数

        异常
        ----------
        KeyError
            如果传入无效 stage
        """
        try:
            return KC_TABLE[stage]
        except KeyError:
            raise KeyError(f"未知的生育阶段: {stage}")

    def get_etc(self, stage: GrowthStage, et0_mm_day: float) -> float:
        """计算作物蒸散发量 ETc = Kc * ET0。

        参数
        ----------
        stage : GrowthStage
            当前生育阶段
        et0_mm_day : float
            参考蒸散发量 (mm/day)

        返回
        ----------
        etc : float
            作物蒸散发量 (mm/day)
        """
        kc = self.get_kc(stage)
        return kc * et0_mm_day

    def get_target_ec(self, stage: GrowthStage) -> float:
        """返回指定生育期的最优土壤 EC (dS/m)。"""
        try:
            return TARGET_EC_TABLE[stage]
        except KeyError:
            raise KeyError(f"未知的生育阶段: {stage}")

    def get_root_depth(self, stage: GrowthStage) -> float:
        """返回指定生育期 80% 根系分布深度 (mm)，来自论文实测数据。"""
        try:
            return ROOT_DEPTH_TABLE[stage]
        except KeyError:
            raise KeyError(f"未知的生育阶段: {stage}")
