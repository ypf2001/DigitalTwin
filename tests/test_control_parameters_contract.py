from pathlib import Path

import yaml

from plc_client import PLCClient


ROOT = Path(__file__).resolve().parents[1]
SIMULATION_PATH = ROOT / "config" / "simulation.yaml"
CONTROL_PATH = ROOT / "config" / "control_parameters.yaml"
SCL_PATH = ROOT / "plc" / "xiaweiji" / "src" / "xiaweiji.scl"


class MemoryPLC:
    def __init__(self, size: int = 528):
        self.memory = bytearray(size)

    def db_read(self, db_number: int, start: int, size: int):
        return self.memory[start:start + size]

    def db_write(self, db_number: int, start: int, data):
        self.memory[start:start + len(data)] = data


def make_client() -> PLCClient:
    config = yaml.safe_load(SIMULATION_PATH.read_text(encoding="utf-8"))
    plc = PLCClient.__new__(PLCClient)
    plc.db_number = 1
    plc.addr_map = config["plc"]["addresses"]
    plc._client = MemoryPLC()
    plc._ensure_connected = lambda: None
    return plc


def test_control_parameter_addresses_are_unique_and_appended():
    config = yaml.safe_load(SIMULATION_PATH.read_text(encoding="utf-8"))
    addresses = config["plc"]["addresses"]
    used = {}
    for name, spec in addresses.items():
        offset = int(spec["offset"])
        if spec.get("type") == "bool":
            keys = [(offset, int(spec.get("bit", 0)))]
        else:
            keys = [(byte, None) for byte in range(offset, offset + int(spec["bytes"]))]
        for key in keys:
            assert key not in used, f"{name} overlaps {used[key]} at {key}"
            used[key] = name

    new_names = {
        "G_EC_F", "G_EC_A", "G_pH_F", "G_pH_A", "Decoupler_Enable",
        "Decoupler_Valid", "Decoupler_Determinant", "Delta_q_f", "Delta_q_a",
    }
    assert min(addresses[name]["offset"] for name in new_names) >= 464


def test_control_parameter_write_keeps_decoupler_disabled_until_explicit_enable():
    parameters = yaml.safe_load(CONTROL_PATH.read_text(encoding="utf-8"))
    plc = make_client()

    assert plc.write_control_parameters(parameters)
    readback = plc.read_control_parameters()
    assert readback["flat"]["Decoupler_Enable"] is False
    assert readback["flat"]["G_EC_F"] == 0.0
    assert readback["flat"]["N_Enable"] == 1.0
    assert readback["flat"]["P_Enable"] == 0.0
    assert plc.set_decoupler_enabled(True) is False

    plc._write_bool("Decoupler_Valid", True)
    assert plc.set_decoupler_enabled(True)
    assert plc.read_control_parameters()["flat"]["Decoupler_Enable"] is True


def test_control_parameter_write_rejects_invalid_limits():
    parameters = yaml.safe_load(CONTROL_PATH.read_text(encoding="utf-8"))
    parameters["limits"]["q_f_max"] = 0.0
    plc = make_client()

    assert plc.write_control_parameters(parameters) is False


def test_plc_validates_decoupler_before_future_execution():
    scl = SCL_PATH.read_text(encoding="utf-8")
    assert '"DB1".Decoupler_Determinant := "DB1".G_EC_F * "DB1".G_pH_A' in scl
    assert '"DB1".Decoupler_Valid := ("DB1".Decoupler_Determinant_Min > 0.0)' in scl
    assert 'q_f_min := "DB1".q_f_min' in scl
    assert 'q_a_max := "DB1".q_a_max' in scl
