"""分层土壤数字孪生 V2。

四层水分、盐分、pH 与 N/P/K 质量平衡模型。参数集中在配置文件中，
后续可以直接替换为真实田间标定参数，不需要改 SAC 或 PLC 主流程。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable
import copy

import numpy as np

from config_loader import load_config


NUTRIENTS = ("n", "p", "k")
STAGE_ALIASES = {
    "ini": "emergence",
    "dev": "tuber_init",
    "mid": "bulking",
    "late": "starch_accumulation",
}


def _array(values: Iterable[float], name: str, size: int | None = None) -> np.ndarray:
    result = np.asarray(list(values), dtype=np.float64)
    if result.ndim != 1 or result.size == 0:
        raise ValueError(f"{name} 必须是一维非空数组")
    if size is not None and result.size != size:
        raise ValueError(f"{name} 长度应为 {size}，实际为 {result.size}")
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{name} 包含非有限值")
    return result


def sample_soil_config(config: Dict[str, Any], rng: np.random.RandomState) -> Dict[str, Any]:
    """Sample soil parameters within configured relative uncertainty ranges.

    Paths are read from ``domain_randomization.relative_range``. A range of
    0.20 samples uniformly from 80% to 120% of the nominal value. Array
    parameters share one multiplier so relative layer differences are kept.
    """
    sampled = copy.deepcopy(config)
    ranges = sampled.get("domain_randomization", {}).get("relative_range", {})
    for dotted_path, relative_range in ranges.items():
        keys = str(dotted_path).split(".")
        node = sampled
        for key in keys[:-1]:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if not isinstance(node, dict) or keys[-1] not in node:
            continue
        spread = max(0.0, float(relative_range))
        factor = float(rng.uniform(max(0.05, 1.0 - spread), 1.0 + spread))
        value = node[keys[-1]]
        if isinstance(value, list):
            node[keys[-1]] = [float(x) * factor for x in value]
        elif isinstance(value, (int, float)):
            node[keys[-1]] = float(value) * factor
    return sampled


class LayeredSoilProfile:
    """可配置的分层土壤水盐、pH 和 N/P/K 模型。"""

    model_name = "layered_v2"

    def __init__(self, config: Dict[str, Any] | None = None, area_ha: float | None = None):
        self.config = dict(config if config is not None else load_config().soil_v2())
        if not self.config:
            raise ValueError("缺少 soil_v2 配置，请检查 config/soil_v2.yaml")

        p = self.config["profile"]
        self.layer_thickness_mm = _array(p["layer_thickness_mm"], "layer_thickness_mm")
        self.n_layers = int(self.layer_thickness_mm.size)
        self.theta_sat_profile = _array(p["theta_sat"], "theta_sat", self.n_layers)
        self.theta_fc_profile = _array(p["theta_fc"], "theta_fc", self.n_layers)
        self.theta_wp_profile = _array(p["theta_wp"], "theta_wp", self.n_layers)
        self.k_sat_mm_h = _array(p["k_sat_mm_h"], "k_sat_mm_h", self.n_layers)
        self.drainage_beta = _array(p["drainage_beta"], "drainage_beta", self.n_layers)
        self.theta_init = _array(p["theta_init"], "theta_init", self.n_layers)
        self.ec_init = _array(p["ec_init_ds_m"], "ec_init_ds_m", self.n_layers)
        self.ph_init = _array(p["ph_init"], "ph_init", self.n_layers)
        if np.any(self.theta_wp_profile >= self.theta_fc_profile) or np.any(
                self.theta_fc_profile >= self.theta_sat_profile):
            raise ValueError("含水率参数必须满足 theta_wp < theta_fc < theta_sat")

        self.area_ha = float(area_ha if area_ha is not None else p.get("area_ha", 1.0))
        if self.area_ha <= 0.0:
            raise ValueError("area_ha 必须大于 0")
        self.area_m2 = self.area_ha * 10000.0
        self.soil_mass_kg_m2 = float(p["bulk_density_kg_m3"]) * self.layer_thickness_mm / 1000.0
        self.fc_drain_fraction = float(p.get("field_capacity_drain_fraction", 0.65))
        self.unsat_drain_fraction = float(p.get("unsaturated_drain_fraction", 0.015))

        # Field-identifiable effective factors absorb irrigation uniformity, ET bias,
        # EC scale error, and simplified salt-transport effects.
        forcing = self.config.get("forcing", {})
        self.irrigation_efficiency = float(np.clip(forcing.get("irrigation_efficiency", 1.0), 0.0, 1.0))
        self.et_scale = max(0.0, float(forcing.get("et_scale", 1.0)))
        salinity = self.config.get("salinity", {})
        self.ec_input_scale = max(0.0, float(salinity.get("input_ec_scale", 1.0)))
        self.salt_transport_efficiency = float(
            np.clip(salinity.get("transport_efficiency", 1.0), 0.0, 1.0)
        )

        ph = self.config["ph"]
        self.ph_buffer_mm = _array(ph["buffer_water_equivalent_mm"], "ph_buffer", self.n_layers)
        self.ph_equilibrium = _array(ph["equilibrium_ph"], "equilibrium_ph", self.n_layers)
        self.ph_irrigation_response = float(ph.get("irrigation_response_fraction", 0.18))
        self.ph_percolation_response = float(ph.get("percolation_response_fraction", 0.12))
        self.ph_recovery_per_day = float(ph.get("recovery_per_day", 0.002))
        self.ph_min = float(ph.get("min_ph", 4.0))
        self.ph_max = float(ph.get("max_ph", 9.5))

        n = self.config["nutrients"]
        self.stock_mg_l = {x: float(n["stock_mg_l"][x]) for x in NUTRIENTS}
        self.mobile_fraction = {x: float(n["mobile_fraction"][x]) for x in NUTRIENTS}
        self.mineralization = {x: float(n["mineralization_mg_m2_day"][x]) for x in NUTRIENTS}
        self.uptake_by_stage = n["uptake_mg_m2_day"]
        self.nutrient_targets_by_stage = n.get("target_mg_kg", {})
        self.stage_recipe = self.config["stage_recipe"]
        self.root_distribution = self.config["root_distribution"]
        self.nutrient_init = {
            x: _array(n["initial_mg_kg"][x], f"initial_mg_kg.{x}", self.n_layers)
            for x in NUTRIENTS
        }
        self.current_stage = "emergence"
        self.root_depth = min(200.0, float(np.sum(self.layer_thickness_mm)))
        self._last_diagnostics: Dict[str, Any] = {}
        self.reset()

    @staticmethod
    def _stage_key(stage: Any) -> str:
        value = getattr(stage, "value", stage)
        key = str(value).strip().lower()
        return STAGE_ALIASES.get(key, key)

    def set_growth_stage(self, stage: Any, root_depth_mm: float | None = None) -> None:
        """更新生育阶段和有效根深。"""
        key = self._stage_key(stage)
        if key in self.root_distribution:
            self.current_stage = key
        if root_depth_mm is not None:
            self.root_depth = float(
                np.clip(root_depth_mm, 1.0, float(np.sum(self.layer_thickness_mm)))
            )

    def _root_weights(self, stage: Any | None = None) -> np.ndarray:
        key = self._stage_key(stage) if stage is not None else self.current_stage
        weights = _array(
            self.root_distribution.get(key, np.ones(self.n_layers)),
            f"root_distribution.{key}",
            self.n_layers,
        )
        tops = np.concatenate(([0.0], np.cumsum(self.layer_thickness_mm)[:-1]))
        overlap = np.clip(self.root_depth - tops, 0.0, self.layer_thickness_mm)
        weights = np.maximum(0.0, weights) * overlap / self.layer_thickness_mm
        total = float(np.sum(weights))
        if total <= 1e-12:
            weights[:] = 0.0
            weights[0] = 1.0
            return weights
        return weights / total

    @property
    def theta(self) -> float:
        return float(np.dot(self._root_weights(), self.theta_profile))

    @property
    def ec_soil(self) -> float:
        return float(np.dot(self._root_weights(), self.ec_profile))

    @ec_soil.setter
    def ec_soil(self, value: float) -> None:
        """Set a uniform EC profile while preserving salt-mass consistency.

        The legacy lumped soil model exposed ``ec_soil`` as a writable scalar.
        Keeping that interface lets commissioning and PLC/HIL scripts initialize
        the layered model without reaching into its internal profile arrays.
        """
        ec = float(value)
        if not np.isfinite(ec) or ec < 0.0:
            raise ValueError("ec_soil must be a finite non-negative value")
        self.ec_profile.fill(ec)
        self.salt_mass = self.ec_profile * self.water_mm
        self._last_diagnostics = self._diagnostics_base()

    @property
    def ph_soil(self) -> float:
        return float(np.dot(self._root_weights(), self.ph_profile))

    @property
    def theta_fc(self) -> float:
        return float(np.dot(self._root_weights(), self.theta_fc_profile))

    @property
    def theta_wp(self) -> float:
        return float(np.dot(self._root_weights(), self.theta_wp_profile))

    def _root_nutrient(self, name: str) -> float:
        concentration = self.nutrient_mass[name] / self.soil_mass_kg_m2
        return float(np.dot(self._root_weights(), concentration))

    @property
    def n_actual(self) -> float:
        return self._root_nutrient("n")

    @property
    def p_actual(self) -> float:
        return self._root_nutrient("p")

    @property
    def k_actual(self) -> float:
        return self._root_nutrient("k")

    def reset(self) -> None:
        """恢复配置中的初始剖面状态。"""
        self.theta_profile = np.clip(
            self.theta_init.copy(), self.theta_wp_profile, self.theta_sat_profile
        )
        self.ec_profile = np.maximum(0.0, self.ec_init.copy())
        self.ph_profile = np.clip(self.ph_init.copy(), self.ph_min, self.ph_max)
        self.water_mm = self.theta_profile * self.layer_thickness_mm
        self.salt_mass = self.ec_profile * self.water_mm
        self.nutrient_mass = {
            x: np.maximum(0.0, self.nutrient_init[x]) * self.soil_mass_kg_m2
            for x in NUTRIENTS
        }
        self._last_diagnostics = self._diagnostics_base()

    def _mix_ph(self, layer: int, water_mm: float, ph_in: float, response: float) -> None:
        if water_mm <= 0.0:
            return
        denominator = self.water_mm[layer] + water_mm + self.ph_buffer_mm[layer]
        fraction = response * water_mm / max(denominator, 1e-9)
        self.ph_profile[layer] += fraction * (float(ph_in) - self.ph_profile[layer])

    def _add_fertilizer(self, q_f_l_min: float, dt_hours: float, stage: str) -> Dict[str, float]:
        volume_l_m2 = max(0.0, float(q_f_l_min)) * 60.0 * dt_hours / self.area_m2
        recipe = self.stage_recipe.get(stage, self.stage_recipe[self.current_stage])
        total = sum(max(0.0, float(recipe.get(x, 0.0))) for x in NUTRIENTS)
        inputs = {x: 0.0 for x in NUTRIENTS}
        if total <= 1e-12 or volume_l_m2 <= 0.0:
            return inputs
        for name in NUTRIENTS:
            fraction = max(0.0, float(recipe.get(name, 0.0))) / total
            inputs[name] = volume_l_m2 * self.stock_mg_l[name] * fraction
            self.nutrient_mass[name][0] += inputs[name]
        return inputs

    def _recipe_fractions(self, stage: str) -> Dict[str, float]:
        recipe = self.stage_recipe.get(stage, self.stage_recipe[self.current_stage])
        total = sum(max(0.0, float(recipe.get(x, 0.0))) for x in NUTRIENTS)
        if total <= 1e-12:
            return {x: 0.0 for x in NUTRIENTS}
        return {x: max(0.0, float(recipe.get(x, 0.0))) / total for x in NUTRIENTS}

    def _nutrient_targets(self, stage: str | None = None) -> Dict[str, float]:
        stage_key = stage or self.current_stage
        targets = self.nutrient_targets_by_stage.get(stage_key, {})
        return {x: float(targets.get(x, 0.0)) for x in NUTRIENTS}

    def _transport(self, dt_hours: float):
        drainage_mm = 0.0
        salt_drained = 0.0
        leached = {x: 0.0 for x in NUTRIENTS}
        for layer in range(self.n_layers):
            thickness = self.layer_thickness_mm[layer]
            theta = self.water_mm[layer] / thickness
            available = max(0.0, self.water_mm[layer] - self.theta_wp_profile[layer] * thickness)
            saturation_excess = max(
                0.0, self.water_mm[layer] - self.theta_sat_profile[layer] * thickness
            )
            relative_saturation = np.clip(
                (theta - self.theta_wp_profile[layer])
                / (self.theta_sat_profile[layer] - self.theta_wp_profile[layer]),
                0.0, 1.0,
            )
            if theta > self.theta_fc_profile[layer]:
                relative_excess = np.clip(
                    (theta - self.theta_fc_profile[layer])
                    / (self.theta_sat_profile[layer] - self.theta_fc_profile[layer]),
                    0.0, 1.0,
                )
                gravity = (self.k_sat_mm_h[layer] * dt_hours
                           * relative_excess ** self.drainage_beta[layer]
                           * self.fc_drain_fraction)
            else:
                gravity = (self.k_sat_mm_h[layer] * dt_hours
                           * relative_saturation ** self.drainage_beta[layer]
                           * self.unsat_drain_fraction)
            outflow = min(available, max(saturation_excess, gravity))
            if outflow <= 0.0:
                continue

            water_fraction = min(1.0, outflow / max(self.water_mm[layer], 1e-12))
            salt_out = (self.salt_mass[layer] * water_fraction
                        * self.salt_transport_efficiency)
            nutrient_out = {
                x: self.nutrient_mass[x][layer] * water_fraction
                * np.clip(self.mobile_fraction[x], 0.0, 1.0)
                for x in NUTRIENTS
            }
            source_ph = float(self.ph_profile[layer])
            self.water_mm[layer] -= outflow
            self.salt_mass[layer] -= salt_out
            for name in NUTRIENTS:
                self.nutrient_mass[name][layer] -= nutrient_out[name]

            if layer + 1 < self.n_layers:
                target = layer + 1
                self._mix_ph(target, outflow, source_ph, self.ph_percolation_response)
                self.water_mm[target] += outflow
                self.salt_mass[target] += salt_out
                for name in NUTRIENTS:
                    self.nutrient_mass[name][target] += nutrient_out[name]
            else:
                drainage_mm += outflow
                salt_drained += salt_out
                for name in NUTRIENTS:
                    leached[name] += nutrient_out[name]
        return drainage_mm, salt_drained, leached

    def _remove_et(self, et_mm: float, root_weights: np.ndarray) -> float:
        remaining, removed = max(0.0, et_mm), 0.0
        active = root_weights.copy()
        for _ in range(self.n_layers):
            if remaining <= 1e-12 or float(np.sum(active)) <= 1e-12:
                break
            allocation = remaining * active / np.sum(active)
            available = np.maximum(
                0.0, self.water_mm - self.theta_wp_profile * self.layer_thickness_mm
            )
            take = np.minimum(allocation, available)
            self.water_mm -= take
            step_removed = float(np.sum(take))
            removed += step_removed
            remaining -= step_removed
            active[available <= allocation + 1e-12] = 0.0
        return removed

    def _update_nutrients(self, dt_hours: float, stage: str, root_weights: np.ndarray):
        uptake_cfg = self.uptake_by_stage.get(stage, self.uptake_by_stage[self.current_stage])
        water_stress = np.clip(
            (self.theta_profile - self.theta_wp_profile)
            / (self.theta_fc_profile - self.theta_wp_profile), 0.0, 1.0
        )
        uptake, mineralized = {}, {}
        for name in NUTRIENTS:
            source = self.mineralization[name] * dt_hours / 24.0
            self.nutrient_mass[name] += source * root_weights
            mineralized[name] = source
            demand = max(0.0, float(uptake_cfg[name])) * dt_hours / 24.0
            actual = np.minimum(
                self.nutrient_mass[name], demand * root_weights * water_stress
            )
            self.nutrient_mass[name] -= actual
            uptake[name] = float(np.sum(actual))
        return uptake, mineralized

    def step(self, I: float, EC_in: float, ET: float, dt_hours: float = 1.0,
             *, ph_in: float = 7.0, q_f_l_min: float = 0.0,
             stage: Any | None = None):
        """推进一步，返回旧接口兼容的根区 theta 和 ec_soil。"""
        dt_hours = float(dt_hours)
        if dt_hours <= 0.0:
            raise ValueError("dt_hours 必须大于 0")
        stage_key = self._stage_key(stage) if stage is not None else self.current_stage
        if stage_key not in self.root_distribution:
            stage_key = self.current_stage
        self.current_stage = stage_key
        root_weights = self._root_weights(stage_key)

        water_before = float(np.sum(self.water_mm))
        salt_before = float(np.sum(self.salt_mass))
        nutrient_before = {x: float(np.sum(self.nutrient_mass[x])) for x in NUTRIENTS}

        gross_irrigation_mm = max(0.0, float(I)) * dt_hours
        irrigation_mm = gross_irrigation_mm * self.irrigation_efficiency
        surface_runoff_mm = gross_irrigation_mm - irrigation_mm
        salt_input = irrigation_mm * max(0.0, float(EC_in)) * self.ec_input_scale
        self._mix_ph(0, irrigation_mm, ph_in, self.ph_irrigation_response)
        self.water_mm[0] += irrigation_mm
        self.salt_mass[0] += salt_input
        fertilizer_input = self._add_fertilizer(q_f_l_min, dt_hours, stage_key)
        recipe_fractions = self._recipe_fractions(stage_key)
        nutrient_targets = self._nutrient_targets(stage_key)

        drainage_mm, salt_drained, leached = self._transport(dt_hours)
        actual_et_mm = self._remove_et(
            max(0.0, float(ET)) * dt_hours * self.et_scale, root_weights
        )
        self.theta_profile = np.clip(
            self.water_mm / self.layer_thickness_mm,
            self.theta_wp_profile, self.theta_sat_profile,
        )
        self.water_mm = self.theta_profile * self.layer_thickness_mm
        uptake, mineralized = self._update_nutrients(dt_hours, stage_key, root_weights)
        for name in NUTRIENTS:
            self.nutrient_mass[name] = np.maximum(0.0, self.nutrient_mass[name])

        recovery = np.clip(self.ph_recovery_per_day * dt_hours / 24.0, 0.0, 1.0)
        self.ph_profile += recovery * (self.ph_equilibrium - self.ph_profile)
        self.ph_profile = np.clip(self.ph_profile, self.ph_min, self.ph_max)
        self.ec_profile = np.divide(
            self.salt_mass, self.water_mm, out=np.zeros_like(self.salt_mass),
            where=self.water_mm > 1e-12,
        )
        self.ec_profile = np.maximum(0.0, self.ec_profile)

        water_after = float(np.sum(self.water_mm))
        salt_after = float(np.sum(self.salt_mass))
        nutrient_after = {x: float(np.sum(self.nutrient_mass[x])) for x in NUTRIENTS}
        nutrient_error = {
            x: nutrient_after[x] - nutrient_before[x] - fertilizer_input[x]
            - mineralized[x] + uptake[x] + leached[x]
            for x in NUTRIENTS
        }
        self._last_diagnostics = self._diagnostics_base()
        self._last_diagnostics.update({
            "drainage_mm": float(drainage_mm),
            "actual_et_mm": float(actual_et_mm),
            "surface_runoff_mm": float(surface_runoff_mm),
            "gross_irrigation_mm": float(gross_irrigation_mm),
            "effective_irrigation_mm": float(irrigation_mm),
            "fertilizer_input_mg_m2": dict(fertilizer_input),
            "q_n_cmd": max(0.0, float(q_f_l_min)) * recipe_fractions["n"],
            "q_p_cmd": max(0.0, float(q_f_l_min)) * recipe_fractions["p"],
            "q_k_cmd": max(0.0, float(q_f_l_min)) * recipe_fractions["k"],
            "n_target": nutrient_targets["n"],
            "p_target": nutrient_targets["p"],
            "k_target": nutrient_targets["k"],
            "nutrient_uptake_mg_m2": dict(uptake),
            "nutrient_leached_mg_m2": dict(leached),
            "water_balance_error_mm": water_after - water_before - irrigation_mm
                                      + actual_et_mm + drainage_mm,
            "salt_balance_error": salt_after - salt_before - salt_input + salt_drained,
            "nutrient_balance_error_mg_m2": nutrient_error,
        })
        return self.theta, self.ec_soil

    def _diagnostics_base(self) -> Dict[str, Any]:
        return {
            "soil_model": self.model_name,
            "parameter_status": self.config.get("parameter_status", "unknown"),
            "parameter_version": self.config.get("parameter_version", "unknown"),
            "theta_profile": self.theta_profile.astype(float).tolist(),
            "ec_profile": self.ec_profile.astype(float).tolist(),
            "ph_profile": self.ph_profile.astype(float).tolist(),
            "n_profile": (self.nutrient_mass["n"] / self.soil_mass_kg_m2).astype(float).tolist(),
            "p_profile": (self.nutrient_mass["p"] / self.soil_mass_kg_m2).astype(float).tolist(),
            "k_profile": (self.nutrient_mass["k"] / self.soil_mass_kg_m2).astype(float).tolist(),
            "soil_ph": self.ph_soil,
            "n_actual": self.n_actual,
            "p_actual": self.p_actual,
            "k_actual": self.k_actual,
            "n_target": self._nutrient_targets()["n"],
            "p_target": self._nutrient_targets()["p"],
            "k_target": self._nutrient_targets()["k"],
            "q_n_cmd": 0.0,
            "q_p_cmd": 0.0,
            "q_k_cmd": 0.0,
            "root_weights": self._root_weights().astype(float).tolist(),
            "irrigation_efficiency": self.irrigation_efficiency,
            "et_scale": self.et_scale,
            "ec_input_scale": self.ec_input_scale,
            "salt_transport_efficiency": self.salt_transport_efficiency,
        }

    def diagnostics(self) -> Dict[str, Any]:
        """返回上一步剖面状态和质量守恒诊断的副本。"""
        result = dict(self._last_diagnostics)
        for key, value in list(result.items()):
            if isinstance(value, dict):
                result[key] = dict(value)
            elif isinstance(value, list):
                result[key] = list(value)
        return result
