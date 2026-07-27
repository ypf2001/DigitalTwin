"""Residual SAC action projection and season-level safety budgets.

The learned action is deliberately small and dimensionless:
``[water_multiplier, ec_residual_ds_m]``.  PLC pH control remains an
independent acid-only safety-band function.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from config_loader import load_config


@dataclass(frozen=True)
class ResidualAction:
    water_multiplier: float
    ec_residual_ds_m: float
    ec_set: float
    ph_nominal: float
    clipped: bool


class ResidualActionProjector:
    """Project raw policy actions into the preregistered safe action set."""

    def __init__(self, action_config: dict | None = None, experiment_config: dict | None = None):
        cfg = load_config()
        self.action_config = action_config or cfg.action()
        experiment = experiment_config or cfg.thesis_experiment_v2()
        residual = experiment.get("residual_policy", {})
        ph_band = experiment.get("ph_band", {})

        self.water_min = float(residual.get("water_multiplier_min", 0.8))
        self.water_max = float(residual.get("water_multiplier_max", 1.2))
        self.ec_residual_min = float(residual.get("ec_residual_min", -0.15))
        self.ec_residual_max = float(residual.get("ec_residual_max", 0.15))
        self.ec_set_min = float(self.action_config.get("ec_set_min", 0.7))
        self.ec_set_max = float(self.action_config.get("ec_set_max", 1.7))
        self.ph_nominal = float(ph_band.get("nominal", 6.2))

    @property
    def low(self) -> np.ndarray:
        return np.array([self.water_min, self.ec_residual_min], dtype=np.float32)

    @property
    def high(self) -> np.ndarray:
        return np.array([self.water_max, self.ec_residual_max], dtype=np.float32)

    def project(self, action, stage_ec: float) -> ResidualAction:
        values = np.asarray(action, dtype=np.float64).reshape(-1)
        if values.size != 2 or not np.all(np.isfinite(values)):
            raise ValueError("residual action must contain two finite values")

        water = float(np.clip(values[0], self.water_min, self.water_max))
        residual = float(np.clip(values[1], self.ec_residual_min, self.ec_residual_max))
        ec_set = float(np.clip(float(stage_ec) + residual, self.ec_set_min, self.ec_set_max))
        clipped = (
            water != float(values[0])
            or residual != float(values[1])
            or abs(ec_set - (float(stage_ec) + residual)) > 1e-12
        )
        return ResidualAction(water, residual, ec_set, self.ph_nominal, clipped)


class SeasonBudgetGuard:
    """Project event water and fertilizer requests onto cumulative budgets."""

    def __init__(self, baseline_water_l: float, baseline_nutrient_g: float,
                 experiment_config: dict | None = None):
        experiment = experiment_config or load_config().thesis_experiment_v2()
        residual = experiment.get("residual_policy", {})
        self.baseline_water_l = float(baseline_water_l)
        self.baseline_nutrient_g = float(baseline_nutrient_g)
        self.water_max_l = self.baseline_water_l * float(
            residual.get("season_water_multiplier_max", 1.10)
        )
        self.water_min_l = self.baseline_water_l * float(
            residual.get("season_water_multiplier_min", 0.90)
        )
        nutrient_error = float(residual.get("season_nutrient_error_max", 0.02))
        self.nutrient_min_g = self.baseline_nutrient_g * (1.0 - nutrient_error)
        self.nutrient_max_g = self.baseline_nutrient_g * (1.0 + nutrient_error)
        self.water_used_l = 0.0
        self.nutrient_used_g = 0.0

    def project_event(
        self,
        water_l: float,
        nutrient_g: float,
        remaining_baseline_water_l: float = 0.0,
        remaining_baseline_nutrient_g: float = 0.0,
    ) -> tuple[float, float, bool]:
        """Project one event while reserving enough future capacity.

        ``remaining_baseline_*`` excludes the current event.  Supplying these
        values prevents a series of low actions from making the preregistered
        season minimum impossible to recover at the final event.
        """
        requested_water = max(float(water_l), 0.0)
        requested_nutrient = max(float(nutrient_g), 0.0)
        residual = load_config().thesis_experiment_v2().get("residual_policy", {})
        future_water_max = max(float(remaining_baseline_water_l), 0.0) * float(
            residual.get("water_multiplier_max", 1.2)
        )
        stage_dev = float(residual.get("stage_nutrient_deviation_max", 0.10))
        future_nutrient_max = max(float(remaining_baseline_nutrient_g), 0.0) * (1.0 + stage_dev)

        water_floor = max(0.0, self.water_min_l - self.water_used_l - future_water_max)
        nutrient_floor = max(
            0.0,
            self.nutrient_min_g - self.nutrient_used_g - future_nutrient_max,
        )
        safe_water = min(
            max(requested_water, water_floor),
            max(0.0, self.water_max_l - self.water_used_l),
        )
        safe_nutrient = min(
            max(requested_nutrient, nutrient_floor),
            max(0.0, self.nutrient_max_g - self.nutrient_used_g),
        )
        limited = (
            abs(safe_water - requested_water) > 1e-12
            or abs(safe_nutrient - requested_nutrient) > 1e-12
        )
        self.water_used_l += safe_water
        self.nutrient_used_g += safe_nutrient
        return safe_water, safe_nutrient, limited


class NutrientBudgetProjector:
    """Bound N/P2O5/K2O allocations by stage and whole-season budgets."""

    NUTRIENTS = ("n", "p2o5", "k2o")

    def __init__(self, experiment_config: dict | None = None):
        experiment = experiment_config or load_config().thesis_experiment_v2()
        budget = experiment.get("nutrient_budget", {})
        residual = experiment.get("residual_policy", {})
        self.total = {key: float(budget.get("per_pot_g", {}).get(key, 0.0))
                      for key in self.NUTRIENTS}
        self.stage_fraction = budget.get("stage_fraction", {})
        self.stage_deviation = float(residual.get("stage_nutrient_deviation_max", 0.10))
        self.season_error = float(residual.get("season_nutrient_error_max", 0.02))
        self.used = {key: 0.0 for key in self.NUTRIENTS}
        self._projected_stages: set[str] = set()

    def nominal_stage(self, stage: str) -> dict[str, float]:
        fractions = self.stage_fraction.get(str(stage).upper(), {})
        return {key: self.total[key] * float(fractions.get(key, 0.0))
                for key in self.NUTRIENTS}

    def project_stage(self, stage: str, requested: dict[str, float]) -> tuple[dict[str, float], bool]:
        stage_name = str(stage).upper()
        if stage_name in self._projected_stages:
            raise ValueError(f"stage has already been projected: {stage_name}")
        nominal = self.nominal_stage(stage_name)
        stage_names = {
            str(name).upper() for name, value in self.stage_fraction.items()
            if isinstance(value, dict) and str(name).upper() != "SOURCE_STATUS"
        }
        future_stages = stage_names - self._projected_stages - {stage_name}
        result: dict[str, float] = {}
        limited = False
        for key in self.NUTRIENTS:
            lower = nominal[key] * (1.0 - self.stage_deviation)
            upper = nominal[key] * (1.0 + self.stage_deviation)
            future_upper = sum(
                self.nominal_stage(name)[key] * (1.0 + self.stage_deviation)
                for name in future_stages
            )
            season_lower = self.total[key] * (1.0 - self.season_error)
            season_upper = self.total[key] * (1.0 + self.season_error)
            lower = max(lower, season_lower - self.used[key] - future_upper)
            value = float(np.clip(float(requested.get(key, nominal[key])), lower, upper))
            value = min(value, max(0.0, season_upper - self.used[key]))
            limited = limited or abs(value - float(requested.get(key, nominal[key]))) > 1e-12
            result[key] = value
            self.used[key] += value
        self._projected_stages.add(stage_name)
        return result, limited
