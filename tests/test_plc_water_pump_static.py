from pathlib import Path

from config_loader import reload_config


SCL_PATH = Path(__file__).resolve().parents[1] / "plc" / "xiaweiji" / "src" / "xiaweiji.scl"


def test_water_pump_db_contract_offsets_are_stable():
    addresses = reload_config().plc()["addresses"]

    assert addresses["Water_Enable"]["offset"] == 400
    assert addresses["Qw_Set"]["offset"] == 404
    assert addresses["Qw_Actual"]["offset"] == 408
    assert addresses["Water_Pump_Run_CMD"]["offset"] == 436
    assert addresses["AQ_Water_Pump_Raw"]["offset"] == 438
    assert addresses["Water_Control_Mode"]["offset"] == 440
    assert addresses["Pre_Flush_Ratio"]["offset"] == 444
    assert addresses["Post_Flush_Ratio"]["offset"] == 448
    assert addresses["Water_Batch_Phase"]["offset"] == 460
    assert addresses["Batch_Fertigation_Active"]["offset"] == 462


def test_scl_starts_water_before_enabling_dosing_interlock():
    scl = SCL_PATH.read_text(encoding="utf-8")
    water_call = scl.index('"DB_Pump_Water"(')
    fertilizer_call = scl.index('"DB_Pump_N"(', water_call)

    assert water_call < fertilizer_call
    assert '"DB_Actuator".Water_Flow_OK := "DB1".Water_Flow_OK;' in scl
    assert '("DB1".Qw_Actual >= 20.0)' in scl
    assert 'Water_Flow_OK := "DB_Actuator".Water_Flow_OK' in scl
    assert 'Water_Enable := 0.0;' in scl


def test_scl_accumulates_volume_and_stops_at_target():
    scl = SCL_PATH.read_text(encoding="utf-8")

    assert '"DB1".Water_Volume_Actual := "DB1".Water_Volume_Actual' in scl
    assert 'AND NOT "DB1".Water_Volume_Complete' in scl
    assert '"DB1".Water_Volume_Actual >= "DB1".Water_Volume_SP' in scl


def test_scl_only_enables_dosing_during_the_fertigation_batch_phase():
    scl = SCL_PATH.read_text(encoding="utf-8")

    assert '"DB1".Water_Batch_Phase := 1;' in scl
    assert '"DB1".Water_Batch_Phase := 2;' in scl
    assert '"DB1".Water_Batch_Phase := 3;' in scl
    assert '"DB1".Batch_Fertigation_Active := "DB1".Water_Flow_OK;' in scl
    assert 'Enable := "DB_Actuator".Execution_Enable AND "DB1".Batch_Fertigation_Active' in scl
