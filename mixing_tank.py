"""
混合罐模块 — MixingTank
========================
模拟母液（EC 较高）和酸液与清水在罐中混合的连续搅拌反应器 (CSTR) 模型。

参数默认值从 config.yaml 的 mixing_tank 段读取，传入参数优先。
"""

import math
from config_loader import load_config


class MixingTank:
    """连续搅拌混合罐 (CSTR)。"""

    def __init__(self, volume: float = None,
                 ec_conc: float = None,
                 ph_acid: float = None,
                 ph_water: float = None):
        mt = load_config().mixing_tank()

        self.volume = volume if volume is not None else mt["volume"]
        self.ec_conc = ec_conc if ec_conc is not None else mt["ec_conc"]
        self.ph_acid = ph_acid if ph_acid is not None else mt["ph_acid"]
        self.ph_water = ph_water if ph_water is not None else mt["ph_water"]

        self.ec_out: float = 0.0
        self.ph_out: float = self.ph_water

    def step(self, q_f: float, q_a: float, q_w: float = 50.0):
        """根据母液、酸液和清水流量计算出口 EC 和 pH。

        参数
        ----------
        q_f : float
            母液流量 (L/min)，含高浓度肥料
        q_a : float
            酸液流量 (L/min)，用于调节 pH
        q_w : float
            清水流量 (L/min)，默认 50 L/min

        返回
        ----------
        (ec_out, ph_out) : tuple[float, float]
            混合罐出口的 EC 和 pH
        """
        total_flow = q_f + q_a + q_w
        if total_flow <= 0:
            return self.ec_out, self.ph_out

        # EC 计算：母液与清水混合（酸液不含 EC）
        ec_mixed = (q_f * self.ec_conc) / total_flow

        # pH 计算：酸液与清水混合（母液视为中性）
        # pH 不能直接线性平均，需要用 [H+] 浓度加权
        h_water = 10.0 ** (-self.ph_water)
        h_acid = 10.0 ** (-self.ph_acid)
        h_mixed = (q_w * h_water + q_a * h_acid) / total_flow

        # 计算 pH = -log10([H+])
        ph_mixed = -math.log10(h_mixed) if h_mixed > 0 else self.ph_water

        # 更新内部状态（CSTR 瞬时混合假定）
        self.ec_out = ec_mixed
        self.ph_out = ph_mixed

        return self.ec_out, self.ph_out

    def reset(self):
        """重置出口 EC 和 pH 至清水初始值。"""
        self.ec_out = 0.0
        self.ph_out = self.ph_water
