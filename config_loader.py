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


class _Config:
    """封装 YAML 配置，提供按模块访问的便捷方法。"""

    def __init__(self, data: dict):
        self._data = data

    def raw(self) -> dict:
        return self._data

    def env(self) -> dict:
        return self._data.get("env", {})

    def soil(self) -> dict:
        return self._data.get("soil", {})

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
_config = None


def _load_dir(config_dir: str) -> dict:
    """加载目录下所有 .yaml 文件并合并。"""
    merged = {}
    yaml_files = sorted(_glob.glob(os.path.join(config_dir, "*.yaml")))
    if not yaml_files:
        yaml_files = sorted(_glob.glob(os.path.join(config_dir, "*.yml")))
    for fp in yaml_files:
        with open(fp, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data:
            merged.update(data)
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
    global _config
    if _config is not None:
        return _config

    if path is None:
        config_dir = os.path.join(os.path.dirname(__file__), "config")
        # 新版目录结构优先，回退到单文件
        if os.path.isdir(config_dir):
            data = _load_dir(config_dir)
        else:
            fp = os.path.join(os.path.dirname(__file__), "config.yaml")
            with open(fp, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
    else:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

    _config = _Config(data)
    return _config


def reload_config(path: str = None) -> _Config:
    """强制重新加载配置（忽略缓存）。"""
    global _config
    _config = None
    return load_config(path)
