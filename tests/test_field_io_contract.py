import csv
import hashlib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PLC_ROOT = Path(r"D:\dw_plc\xiaweiji")
SCL = PLC_ROOT / "src" / "xiaweiji.scl"
MIRROR = ROOT / "plc" / "xiaweiji" / "src" / "xiaweiji.scl"
SAFETY_LAD = PLC_ROOT / "src" / "lad" / "程序块" / "FC_FieldSafety_LAD.s7dcl"
OUTPUT_LAD = PLC_ROOT / "src" / "lad" / "程序块" / "FC_FieldOutput_LAD.s7dcl"


def _addresses():
    return yaml.safe_load((ROOT / "config" / "simulation.yaml").read_text(encoding="utf-8"))["plc"]["addresses"]


def test_field_extension_is_append_only_and_bit_packed():
    addresses = _addresses()
    assert addresses["E4_Sim_Step_s"]["offset"] == 760
    assert addresses["Deployment_Mode"] == {"offset": 764, "type": "int", "bytes": 2}
    expected_bits = {
        "Soft_Stop_Request": 0,
        "Actuator_Enable_Request": 1,
        "Field_IO_Ready": 2,
        "Actuator_Enable_Permitted": 3,
        "Physical_EStop_OK": 4,
        "Sensor_Fault_Any": 5,
        "Drive_Fault_Any": 6,
    }
    for name, bit in expected_bits.items():
        assert addresses[name]["offset"] == 766
        assert addresses[name]["bit"] == bit


def test_canonical_and_digital_twin_sources_match():
    assert hashlib.sha256(SCL.read_bytes()).digest() == hashlib.sha256(MIRROR.read_bytes()).digest()


def test_field_scaling_is_scl_and_discrete_safety_is_lad():
    scl = SCL.read_text(encoding="utf-8")
    safety = SAFETY_LAD.read_text(encoding="utf-8-sig")
    assert 'DATA_BLOCK "DB_FieldIO"' in scl
    assert 'FUNCTION "FC_FieldIO" : Void' in scl
    assert 'FOR #i := 1 TO 8 DO' in scl
    assert 'IF "DB1".Deployment_Mode = 1 THEN' in scl
    for condition in (
        'Contact( "DB1".Actuator_Enable_Request )',
        'Contact( "DB_FieldIO".DI_Commissioning_Key_Active )',
        'Contact( "DB1".Physical_EStop_OK )',
        'Contact( "DB1".Field_IO_Ready )',
        'I_Contact( "DB1".Sensor_Fault_Any )',
        'I_Contact( "DB1".Drive_Fault_Any )',
        'I_Contact( "DB1".Soft_Stop_Request )',
    ):
        assert condition in safety


def test_final_physical_outputs_have_one_owner_block():
    output = OUTPUT_LAD.read_text(encoding="utf-8-sig")
    all_other_sources = SCL.read_text(encoding="utf-8") + SAFETY_LAD.read_text(encoding="utf-8-sig")
    for name in (
        "AO_Water_Final", "AO_N_Final", "AO_P_Final", "AO_K_Final", "AO_Acid_Final",
        "DO_Water_Run_Final", "DO_N_Run_Final", "DO_P_Run_Final", "DO_K_Run_Final",
        "DO_Acid_Run_Final",
    ):
        assert name in output
        assert f'"DB_FieldIO".{name}' not in all_other_sources
    assert output.count('I_Contact( "DB1".Actuator_Enable_Permitted )') == 5


def test_hmi_never_writes_emergency_stop_and_protects_engineer_controls():
    rows = list(csv.DictReader(
        (ROOT / "docs" / "HMI标签清单_KTP900.csv").open(encoding="utf-8-sig", newline="")
    ))
    emergency = [row for row in rows if row["TagName"] == "Emergency_Stop"]
    actuator = [row for row in rows if row["TagName"] == "Actuator_Enable_Request"]
    assert emergency and all(row["Access"] == "ReadOnly" for row in emergency)
    assert actuator and all(row["Role"] == "Engineer" for row in actuator)


def test_deployment_profiles_assign_feedback_ownership():
    deployment = yaml.safe_load((ROOT / "config" / "deployment.yaml").read_text(encoding="utf-8"))["deployment"]
    assert deployment["modes"]["simulation_plc"]["feedback_owner"] == "python"
    assert deployment["modes"]["field_plc"]["feedback_owner"] == "plc"
    assert "Emergency_Stop" in deployment["modes"]["field_plc"]["forbidden_remote_write_tags"]
    assert deployment["process_model"]["fertilizer_stock"]["channel_names"] == ["N", "P", "K"]
