from pathlib import Path

from sac_model_registry import get_stage_model_path


def test_v2_stage_model_path_uses_residual_action_name():
    path = get_stage_model_path("MID")
    assert path.name == "sac_residual_mid_final"
    assert "sac_mid_final" not in path.name

