"""
EC/pH 目标值到执行流量的桥接控制器
====================================

B 路线中，SAC 不再直接输出母液/酸液流量，而是输出上层目标值：
    action = [EC_set, pH_set]

本模块负责把 EC_set、pH_set 转换为数字孪生环境可执行的 q_f、q_a。
在真实系统中，这一层应由 PLC 内部的 EC-PID、pH-PID 完成；
在纯仿真中，这里使用混合模型反算近似执行流量，用于训练和评估。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from config_loader import load_config


@dataclass
class SetpointResult:
    """目标值转换结果。"""

    ec_set: float
    ph_set: float
    q_f: float
    q_a: float


class SetpointToFlowController:
    """将 EC/pH 目标值转换为母液流量和酸液流量。

    说明
    ----
    - 这是仿真环境中的“执行层近似”。
    - 真实部署时，推荐 PLC 读取 EC_set/pH_set 后，用在线 EC/pH 反馈做 PID 闭环。
    - 这里使用混合罐静态反算，目的是让 SAC 训练动作从执行量变成上层目标值。
    """

    def __init__(self):
        cfg = load_config()
        action = cfg.action()
        tank = cfg.mixing_tank()

        self.ec_set_min = float(action.get("ec_set_min", 0.8))
        self.ec_set_max = float(action.get("ec_set_max", 2.5))
        self.ph_set_min = float(action.get("ph_set_min", 5.8))
        self.ph_set_max = float(action.get("ph_set_max", 6.8))

        self.q_f_min = float(action.get("q_f_min", 0.0))
        self.q_f_max = float(action.get("q_f_max", 10.0))
        self.q_a_min = float(action.get("q_a_min", 0.0))
        self.q_a_max = float(action.get("q_a_max", 4.0))

        self.ec_conc = float(tank.get("ec_conc", 35.0))
        self.ph_acid = float(tank.get("ph_acid", 3.9))
        self.ph_water = float(tank.get("ph_water", 7.2))

    def clip_setpoint(self, ec_set: float, ph_set: float) -> tuple[float, float]:
        """限制 EC/pH 目标值在安全动作范围内。"""
        ec = float(np.clip(ec_set, self.ec_set_min, self.ec_set_max))
        ph = float(np.clip(ph_set, self.ph_set_min, self.ph_set_max))
        return ec, ph

    def _solve_q_f(self, ec_set: float, q_w: float, q_a: float) -> float:
        """根据目标 EC 反算母液流量。

        混合模型：EC = q_f * EC_conc / (q_w + q_a + q_f)
        反算：q_f = EC * (q_w + q_a) / (EC_conc - EC)
        """
        if ec_set <= 0 or self.ec_conc <= ec_set:
            return self.q_f_max
        q_f = ec_set * (q_w + q_a) / (self.ec_conc - ec_set)
        return float(np.clip(q_f, self.q_f_min, self.q_f_max))

    def _solve_q_a(self, ph_set: float, q_w: float, q_f: float) -> float:
        """根据目标 pH 反算酸液流量。

        pH 混合用 H+ 浓度加权：
        h_set = (q_w*h_water + q_a*h_acid) / (q_w + q_f + q_a)
        反算：q_a = (h_set*(q_w+q_f) - q_w*h_water) / (h_acid - h_set)
        """
        h_set = 10.0 ** (-ph_set)
        h_water = 10.0 ** (-self.ph_water)
        h_acid = 10.0 ** (-self.ph_acid)
        denom = h_acid - h_set
        if denom <= 1e-12:
            return self.q_a_min
        q_a = (h_set * (q_w + q_f) - q_w * h_water) / denom
        return float(np.clip(q_a, self.q_a_min, self.q_a_max))

    def to_flow(self, ec_set: float, ph_set: float, q_w: float) -> SetpointResult:
        """把 EC_set/pH_set 转换为 q_f/q_a。

        由于 EC 和 pH 反算存在轻微耦合，这里做 3 次固定点迭代。
        """
        ec, ph = self.clip_setpoint(ec_set, ph_set)

        q_a = 0.0
        q_f = 0.0
        for _ in range(3):
            q_f = self._solve_q_f(ec, q_w, q_a)
            q_a = self._solve_q_a(ph, q_w, q_f)

        return SetpointResult(ec_set=ec, ph_set=ph, q_f=q_f, q_a=q_a)
