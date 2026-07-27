import numpy as np

from config_loader import reload_config
from residual_action import (
    NutrientBudgetProjector,
    ResidualActionProjector,
    SeasonBudgetGuard,
)


def test_residual_action_projects_to_stage_baseline_and_limits():
    projector = ResidualActionProjector()

    action = projector.project([1.4, 0.30], stage_ec=1.0)

    assert action.water_multiplier == 1.2
    assert action.ec_residual_ds_m == 0.15
    assert action.ec_set == 1.15
    assert action.ph_nominal == 6.2
    assert action.clipped


def test_season_guard_recovers_minimum_after_repeated_low_actions():
    guard = SeasonBudgetGuard(baseline_water_l=8.0, baseline_nutrient_g=0.0)
    delivered = []
    for index in range(8):
        water, _, _ = guard.project_event(
            0.8,
            0.0,
            remaining_baseline_water_l=7 - index,
        )
        delivered.append(water)

    assert sum(delivered) == 7.2
    assert max(delivered) <= 1.2 + 1e-9


def test_nutrient_projector_enforces_stage_and_season_limits():
    projector = NutrientBudgetProjector()
    for stage in ("INI", "DEV", "MID", "LATE"):
        nominal = projector.nominal_stage(stage)
        projector.project_stage(stage, {key: value * 0.5 for key, value in nominal.items()})

    cfg = reload_config().thesis_experiment_v2()["nutrient_budget"]["per_pot_g"]
    for nutrient, total in cfg.items():
        assert total * 0.98 - 1e-9 <= projector.used[nutrient] <= total * 1.02 + 1e-9


def test_nominal_fertilizer_conversion_conserves_npk_budget():
    budget = reload_config().thesis_experiment_v2()["nutrient_budget"]
    masses = budget["nominal_fertilizer_g_per_pot"]
    sources = budget["fertilizer_sources"]
    supplied_n = masses["urea"] * sources["urea"]["n_fraction"]
    supplied_p = masses["monopotassium_phosphate"] * sources["monopotassium_phosphate"]["p2o5_fraction"]
    supplied_k = (
        masses["monopotassium_phosphate"] * sources["monopotassium_phosphate"]["k2o_fraction"]
        + masses["potassium_sulfate"] * sources["potassium_sulfate"]["k2o_fraction"]
    )

    assert np.isclose(supplied_n, budget["per_pot_g"]["n"], atol=0.002)
    assert np.isclose(supplied_p, budget["per_pot_g"]["p2o5"], atol=0.002)
    assert np.isclose(supplied_k, budget["per_pot_g"]["k2o"], atol=0.002)
