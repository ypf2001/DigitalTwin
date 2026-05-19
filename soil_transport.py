"""
土壤运移模块 — SoilTransport
=============================
根区水盐平衡模型，假设瞬时完全混合。

所有参数默认值从 config.yaml 的 soil 段读取。
传入参数优先于配置文件。
"""
from config_loader import load_config


class SoilTransport:
    """根区水分-盐分运移模型（集总参数，瞬间完全混合）。
    物理过程：
      水分: d(theta) = (I - ET - Drain) / root_depth * dt
      盐分: d(EC) = (I*EC_in - Drain*EC*1000) / (theta * root_depth) * dt

    排水量采用幂函数模型：
      Drain_out = K_sat * (theta / theta_sat)^beta * dt

    参数
    ----------
    root_depth : float
        根层深度 (mm)，默认 300
    theta_sat : float
        饱和含水率 (m3/m3)，默认 0.43
    theta_fc : float
        田间持水量 (m3/m3)，默认 0.32
    theta_wp : float
        凋萎点 (m3/m3)，默认 0.04
    k_sat : float
        饱和导水率 (mm/h)，默认 15.3
    beta : float
        排水幂指数，默认 2.0
    theta_init : float
        初始含水率，默认 0.16
    ec_soil_init : float
        初始土壤 EC (dS/m)，默认 0.1
    """
    def __init__(self,
                 root_depth: float = None,
                 theta_sat: float = None,
                 theta_fc: float = None,
                 theta_wp: float = None,
                 K_sat: float = None,
                 beta: float = None,
                 theta_init: float = None,
                 ec_soil_init: float = None):
        soil = load_config().soil()

        self.root_depth = root_depth if root_depth is not None else soil["root_depth_default"]
        self.theta_sat = theta_sat if theta_sat is not None else soil["theta_sat"]
        self.theta_fc = theta_fc if theta_fc is not None else soil["theta_fc"]
        self.theta_wp = theta_wp if theta_wp is not None else soil["theta_wp"]
        self.K_sat = K_sat if K_sat is not None else soil["K_sat"]
        self.beta = beta if beta is not None else soil["beta"]

        self.theta_init = theta_init if theta_init is not None else soil["theta_init"]
        self.ec_soil_init = ec_soil_init if ec_soil_init is not None else soil["ec_soil_init"]
        self.theta: float = self.theta_init
        self.ec_soil: float = self.ec_soil_init

    def _clamp_theta(self, theta: float) -> float:
        """将含水率限制在凋萎点与饱和含水率之间。"""
        return max(self.theta_wp, min(self.theta_sat, theta))

    def step(self, I: float, EC_in: float, ET: float, dt_hours: float = 1.0):
        """运行一个时间步的水盐平衡模拟。

        参数
        ----------
        I : float
            灌溉强度 (mm/h)
        EC_in : float
            灌溉水电导率 (dS/m)
        ET : float
            蒸散发速率 (mm/h)
        dt_hours : float
            时间步长 (h)

        返回
        ----------
        (theta, ec_soil) : tuple[float, float]
            更新后的含水率和土壤 EC
        """
        # 水分平衡
        irrig_vol = I * dt_hours                     # 灌溉入渗量 (mm)
        et_vol = ET * dt_hours                       # 蒸腾消耗量 (mm)
        # 排水仅当 theta > theta_fc (田间持水量以上) 时发生
        if self.theta > self.theta_fc:
            excess = (self.theta - self.theta_fc) / (self.theta_sat - self.theta_fc)
            drain = self.K_sat * excess ** self.beta * dt_hours
        else:
            drain = 0.0

        delta_theta = (irrig_vol - et_vol - drain) / self.root_depth
        theta_new = self._clamp_theta(self.theta + delta_theta)

        # 盐分平衡：d(theta * EC * root_depth) = I*EC_in*dt - Drain*EC_soil
        # 所有项统一用 (mm · dS/m) 量纲
        salt_in = irrig_vol * EC_in
        salt_leach = drain * self.ec_soil
        salt_mass_old = self.theta * self.ec_soil * self.root_depth
        salt_mass_new = salt_mass_old + salt_in - salt_leach

        if theta_new > 1e-8:
            ec_new = max(0.0, salt_mass_new / (theta_new * self.root_depth))
        else:
            ec_new = 0.0

        self.theta = theta_new
        self.ec_soil = ec_new

        return self.theta, self.ec_soil

    def reset(self):
        """重置根区含水率和 EC 至初始值。"""
        self.theta = self.theta_init
        self.ec_soil = self.ec_soil_init
