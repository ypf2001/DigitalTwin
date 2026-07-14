from pathlib import Path

import yaml

from plc_client import PLCClient


ROOT = Path(__file__).resolve().parents[1]
SCL_PATH = ROOT / "plc" / "xiaweiji" / "src" / "xiaweiji.scl"
YAML_PATH = ROOT / "config" / "simulation.yaml"


def test_adaptive_diagnostic_addresses_are_unique():
    addresses = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))["plc"]["addresses"]
    used = {}
    for name, spec in addresses.items():
        offset = int(spec["offset"])
        if spec.get("type") == "bool":
            keys = [(offset, int(spec.get("bit", 0)))]
        else:
            keys = [(byte, None) for byte in range(offset, offset + int(spec.get("bytes", 1)))]
        for key in keys:
            assert key not in used, f"{name} overlaps {used.get(key)} at {key}"
            used[key] = name


def test_read_state_exposes_adaptive_and_npk_diagnostics():
    names = set(PLCClient.read_state.__code__.co_consts)
    required = {
        "Kp_EC_Effective", "Ki_EC_Effective", "Kd_EC_Effective",
        "Kp_pH_Effective", "Ki_pH_Effective", "Kd_pH_Effective",
        "q_f_Feedforward", "q_f_PID_Correction", "q_f_raw",
        "q_a_Feedforward", "q_a_PID_Correction", "q_a_raw",
        "NPK_Optimization_Weight", "NPK_Feedback_Valid",
        "NPK_Capacity_Limited", "Compressed_HIL_Enable",
        "Feedforward_Hold_Active", "Adaptive_PID_Active",
    }
    source = Path(ROOT / "plc_client.py").read_text(encoding="utf-8")
    for name in required:
        assert f'"{name}"' in source


def test_scl_contains_priority_weight_recipe_and_capacity_projection():
    scl = SCL_PATH.read_text(encoding="utf-8")
    assert "#NPK_Max_Control_Error <= 0.01" in scl
    assert "#NPK_Max_Control_Error >= 0.02" in scl
    assert "#NPK_Weight_State := #NPK_Weight_State + 0.5 * #CycleTime" in scl
    assert '"DB1".N_Target := 0.75; "DB1".P_Target := 0.55; "DB1".K_Target := 0.65;' in scl
    assert '"DB1".N_Target := 1.10; "DB1".P_Target := 0.85; "DB1".K_Target := 1.25;' in scl
    assert "#Recipe_N := #Recipe_N / #Recipe_Sum" in scl
    assert "#q_npk_scale := #q_f_cmd / #q_npk_sum" in scl
    assert "#NPK_Capacity_Limited_Out := (#NPK_Total_Capacity + 0.0001) < #q_f_cmd" in scl
    assert "IF #N_Enable < 0.5 THEN #q_n_target := 0.0; END_IF;" in scl


def test_compressed_hil_is_gated_and_cleared_on_timeout():
    scl = SCL_PATH.read_text(encoding="utf-8")
    assert 'Compressed_HIL_Enable := "DB1".Compressed_HIL_Enable AND "DB1".Remote_Comms_OK,' in scl
    assert 'IF #Compressed_HIL_Enable THEN #Hold_Time_S := 1.0; ELSE #Hold_Time_S := 60.0; END_IF;' in scl
    assert '"DB1".Compressed_HIL_Enable := FALSE;' in scl
    assert '"DB1".NPK_Feedback_Valid := FALSE;' in scl


def test_scl_back_calculates_integral_when_dynamic_trim_saturates():
    scl = SCL_PATH.read_text(encoding="utf-8")
    assert "q_f_correction_unlimited : Real;" in scl
    assert "q_a_correction_unlimited : Real;" in scl
    assert "(#q_f_correction - #q_f_correction_unlimited) * #CycleTime / #Ki_EC_Eff" in scl
    assert "(#q_a_correction - #q_a_correction_unlimited) * #CycleTime / #Ki_pH_Eff" in scl
    assert "Ki_EC_Set := 0.030;" in scl
    assert "Ki_pH_Set := 0.010;" in scl