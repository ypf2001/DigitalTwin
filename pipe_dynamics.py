"""
管网传输延迟模块 — PipeDynamics
================================
数学模型: G(s) = e^{-τs} / (T·s + 1)
  - e^{-τs} : 纯滞后环节，用 deque 缓冲实现
  - 1/(T·s+1) : 一阶惯性环节，用后向欧拉离散

参数默认值从 config.yaml 的 pipe 段读取，传入参数优先。
"""

from collections import deque
import logging
from config_loader import load_config

logger = logging.getLogger(__name__)


class PipeDynamics:
    """模拟液肥在管道中的传输延迟与混合衰减。"""

    def __init__(self, tau: float = None, T: float = None, dt: float = 1.0):
        pipe = load_config().pipe()
        self.tau = tau if tau is not None else pipe["tau"]
        self.T = T if T is not None else pipe["T"]
        self.dt = dt

        # 纯滞后所需的缓冲长度 = 滞后时间 / 步长。
        # 当 dt >= tau 时，离散模型无法解析小于一个采样步的纯滞后；
        # 此时仍保留 1 步缓冲，但该滞后只应理解为步长尺度上的近似。
        self._buffer_len = max(1, round(self.tau / self.dt))
        self.delay_resolved = self.dt < self.tau
        if not self.delay_resolved:
            logger.warning(
                "PipeDynamics delay is under-resolved: tau=%.3f min, dt=%.3f min. "
                "Pure delay is approximated by a 1-step buffer.",
                self.tau,
                self.dt,
            )
        self._ec_buffer = deque(maxlen=self._buffer_len)
        self._ph_buffer = deque(maxlen=self._buffer_len)

        # 惯性环节的状态 (上一时刻的输出)
        self.ec_filt: float = 0.0   # EC 滤波值初始 0
        self.ph_filt: float = 7.0   # pH 滤波值初始 7

    def step(self, ec_in: float, ph_in: float):
        """输入混合罐出口的 EC 和 pH，返回经过管道延迟后的值。

        处理流程:
          1. 将当前输入压入 deque（纯滞后）
          2. 从 deque 取出 τ 时间前的数据
          3. 对取出值做一阶惯性滤波（后向欧拉）

        参数
        ----------
        ec_in : float
            混合罐出口 EC (dS/m)
        ph_in : float
            混合罐出口 pH

        返回
        ----------
        (ec_out, ph_out) : tuple[float, float]
            滴头处 EC 和 pH
        """
        # ---- 1. 纯滞后 ----
        self._ec_buffer.append(ec_in)
        self._ph_buffer.append(ph_in)

        # 若缓冲区未满，取最早的值（即为当前的输入）
        ec_delayed = self._ec_buffer[0]
        ph_delayed = self._ph_buffer[0]

        # ---- 2. 一阶惯性滤波 (后向欧拉) ----
        # 离散形式: y(k) = (dt/(T+dt)) * u(k) + (T/(T+dt)) * y(k-1)
        alpha = self.dt / (self.T + self.dt)
        self.ec_filt = alpha * ec_delayed + (1.0 - alpha) * self.ec_filt
        self.ph_filt = alpha * ph_delayed + (1.0 - alpha) * self.ph_filt

        return self.ec_filt, self.ph_filt

    def reset(self):
        """重置所有内部状态至初始值。"""
        self._ec_buffer.clear()
        self._ph_buffer.clear()

        # 填充缓冲区以模拟初始稳态
        init_ec = 0.0
        init_ph = 7.0
        for _ in range(self._buffer_len):
            self._ec_buffer.append(init_ec)
            self._ph_buffer.append(init_ph)

        self.ec_filt = init_ec
        self.ph_filt = init_ph
