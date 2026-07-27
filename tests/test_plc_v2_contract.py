from pathlib import Path

import pytest

from config_loader import reload_config
from plc_client import PLCClient


ROOT = Path(__file__).resolve().parents[1]


class RecordingPLC:
    def __init__(self):
        self.values = {}

    def real(self, name, value):
        self.values[name] = float(value)

    def integer(self, name, value):
        self.values[name] = int(value)


def make_client():
    plc = PLCClient.__new__(PLCClient)
    plc.addr_map = reload_config().plc()["addresses"]
    plc._connected = True
    plc._ensure_connected = lambda: None
    recorder = RecordingPLC()
    plc._write_real = recorder.real
    plc._write_int = recorder.integer
    plc.write_feedback = lambda **kwargs: recorder.values.update(kwargs) is None or True
    return plc, recorder


def test_v2_db1_extension_starts_after_frozen_contract():
    addresses = reload_config().plc()["addresses"]
    assert addresses["Actuator_Any_Trip"]["offset"] == 529
    assert addresses["Water_Multiplier_SP"]["offset"] == 532
    assert addresses["Smith_EC_Predicted"]["offset"] == 600


def test_write_residual_command_resolves_legacy_absolute_target():
    plc, recorder = make_client()

    assert plc.write_residual_command(
        water_multiplier=1.1,
        ec_residual=-0.1,
        stage_ec=1.5,
        ec_actual=1.2,
        ph_actual=6.7,
        recipe_id=2,
        controller_mode=2,
        batch_water_target_l=3.319,
    )

    assert recorder.values["Water_Multiplier_SP"] == pytest.approx(1.1)
    assert recorder.values["EC_Residual_SP"] == pytest.approx(-0.1)
    assert recorder.values["EC_Set_SP"] == pytest.approx(1.4)
    assert recorder.values["pH_Set_SP"] == pytest.approx(6.15)
    assert recorder.values["Recipe_ID"] == 2
    assert recorder.values["Controller_Mode"] == 2


def test_write_residual_command_rejects_out_of_bounds_action():
    plc, _ = make_client()
    with pytest.raises(ValueError):
        plc.write_residual_command(1.3, 0.0, 1.0, 1.0, 6.2)


def test_scl_declares_three_modes_and_safe_unvalidated_smith_status():
    source = (ROOT / "plc" / "xiaweiji" / "src" / "xiaweiji.scl").read_text(encoding="utf-8")
    assert "Controller_Mode : Int" in source
    assert "0=固定PI, 1=非线性增益调度PID, 2=IMC-PI+pH脉冲安全带" in source
    assert "IMC_Smith_Active_Out := FALSE" in source
    assert "pH_Flush_Request_Out" in source
    assert "Batch_Reject_Out" in source
