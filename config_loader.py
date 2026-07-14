"""
配置加载器 — 从 config/ 目录读取 YAML 文件，合并后提供模块化访问。

用法:
    from config_loader import load_config
    cfg = load_config()            # 加载 config/ 目录下所有 .yaml
    cfg = load_config("my.yaml")   # 加载单个配置文件

    # 按模块获取配置
    soil = cfg.soil()
    env   = cfg.env()
    reward = cfg.reward()
"""

import os
import yaml
import glob as _glob
import copy


class _Config:
    """封装 YAML 配置，提供按模块访问的便捷方法。"""

    def __init__(self, data: dict):
        self._data = data

    def raw(self) -> dict:
        return self._data

    def calibration(self) -> dict:
        """Return metadata for the active field-calibration profile."""
        return self._data.get("calibration", {})

    def env(self) -> dict:
        return self._data.get("env", {})

    def soil(self) -> dict:
        return self._data.get("soil", {})

    def soil_v2(self) -> dict:
        """分层土壤数字孪生 V2 参数。"""
        return self._data.get("soil_v2", {})

    def hetao_soil(self) -> dict:
        """河套灌区土壤参数，用于 Python 土壤仿真与 Fluent 建模对齐。"""
        return self._data.get("hetao_soil", {})

    def mixing_tank(self) -> dict:
        return self._data.get("mixing_tank", {})

    def pipe(self) -> dict:
        return self._data.get("pipe", {})

    def crop(self) -> dict:
        return self._data.get("crop", {})

    def crop_stages(self) -> dict:
        return self._data.get("crop", {}).get("stages", {})

    def reward(self) -> dict:
        return self._data.get("reward", {})

    def action(self) -> dict:
        return self._data.get("action", {})

    def obs(self) -> dict:
        return self._data.get("obs", {})

    def day_night(self) -> dict:
        return self._data.get("day_night", {})

    def irrigation(self) -> dict:
        return self._data.get("irrigation", {})

    def plc(self) -> dict:
        return self._data.get("plc", {})

    def deployment(self) -> dict:
        """真实部署/PLCSIM 预检相关参数。"""
        return self._data.get("deployment", {})

    def season_comparison(self) -> dict:
        return self._data.get("season_comparison", {})

    def sac(self) -> dict:
        return self._data.get("sac", {})

    def get(self, key: str, default=None):
        """通用取值，支持点号分隔的嵌套路径。如 cfg.get('soil.K_sat')"""
        keys = key.split(".")
        node = self._data
        for k in keys:
            if isinstance(node, dict):
                node = node.get(k)
            else:
                return default
            if node is None:
                return default
        return node


# ---- 模块级缓存 ----
_config_cache = {}


def _default_config_path() -> str:
    config_dir = os.path.join(os.path.dirname(__file__), "config")
    if os.path.isdir(config_dir):
        return os.path.abspath(config_dir)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "config.yaml"))


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge mappings; overlay leaf values take precedence."""
    result = copy.deepcopy(base)
    for key, value in (overlay or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _active_calibration_path(config_dir: str) -> str | None:
    """Resolve the active field-calibration profile.

    Priority: DT_CALIBRATION_PROFILE, then config/calibration/active.yaml.
    Explicit single-file loads do not receive this overlay.
    """
    env_path = os.getenv("DT_CALIBRATION_PROFILE", "").strip()
    if env_path:
        profile = os.path.abspath(env_path)
        if not os.path.isfile(profile):
            raise FileNotFoundError(f"DT_CALIBRATION_PROFILE does not exist: {profile}")
        return profile
    active = os.path.join(config_dir, "calibration", "active.yaml")
    return active if os.path.isfile(active) else None


def _cache_key(path: str = None) -> str:
    base = _default_config_path() if path is None else os.path.abspath(path)
    if path is not None or not os.path.isdir(base):
        return base
    profile = _active_calibration_path(base)
    if not profile:
        return base
    return f"{base}|calibration={os.path.abspath(profile)}|mtime={os.path.getmtime(profile)}"


def _load_dir(config_dir: str) -> dict:
    """Load top-level YAML files, then apply the active calibration overlay."""
    merged = {}
    yaml_files = sorted(_glob.glob(os.path.join(config_dir, "*.yaml")))
    if not yaml_files:
        yaml_files = sorted(_glob.glob(os.path.join(config_dir, "*.yml")))
    for fp in yaml_files:
        with open(fp, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data:
            merged = _deep_merge(merged, data)

    profile = _active_calibration_path(config_dir)
    if profile:
        with open(profile, "r", encoding="utf-8") as f:
            overlay = yaml.safe_load(f) or {}
        merged = _deep_merge(merged, overlay)
        merged.setdefault("calibration", {})["active_profile"] = os.path.abspath(profile)
    return merged


def load_config(path: str = None) -> _Config:
    """加载配置文件，返回 _Config 对象。

    参数
    ----------
    path : str, optional
        - None: 加载 config/ 目录下所有 .yaml 文件并合并
        - 文件路径: 加载单个 YAML 文件

    返回
    ----------
    _Config
    """
    key = _cache_key(path)
    if key in _config_cache:
        return _config_cache[key]

    if path is None:
        config_dir = _default_config_path()
        # 新版目录结构优先，回退到单文件
        if os.path.isdir(config_dir):
            data = _load_dir(config_dir)
        else:
            with open(config_dir, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
    else:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

    _config_cache[key] = _Config(data)
    return _config_cache[key]


def reload_config(path: str = None) -> _Config:
    """强制重新加载配置（忽略缓存）。"""
    if path is None:
        _config_cache.clear()
    else:
        _config_cache.pop(_cache_key(path), None)
    return load_config(path)
