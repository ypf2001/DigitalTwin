from pathlib import Path

import yaml

from plc_client import PLCClient


ROOT = Path(__file__).resolve().parents[1]
SIMULATION_PATH = ROOT / "config" / "simulation.yaml"
CONTROL_PATH = ROOT / "config" / "control_parameters.yaml"
SCL_PATH = ROOT / "plc" / "xiaweiji" / "src" / "xiaweiji.scl"
MODE_INTERLOCK_LAD_PATH = (
    ROOT / "plc" / "xiaweiji" / "src" / "lad" / "程序块" / "FC_ModeInterlock_LAD.s7dcl"
)


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


def test_plc_validates_and_executes_guarded_local_decoupling():
    scl = SCL_PATH.read_text(encoding="utf-8")
    assert '"DB1".Decoupler_Determinant := "DB1".G_EC_F * "DB1".G_pH_A' in scl
    assert '"DB1".Decoupler_Valid := ("DB1".Decoupler_Determinant_Min > 0.0)' in scl
    assert 'AND (ABS("DB1".Decoupler_Determinant) >= "DB1".Decoupler_Determinant_Min)' in scl
    assert '("DB1".G_EC_F > 0.000001)' in scl
    assert '("DB1".G_pH_A < -0.000001)' in scl
    assert 'q_f_min := "DB1".q_f_min' in scl
    assert 'q_a_max := "DB1".q_a_max' in scl
    assert 'Decoupler_Enable := "DB1".Decoupler_Enable' in scl
    assert "#Coupling_EC_A := #G_EC_A / #G_EC_F;" in scl
    assert "#Coupling_pH_F := #G_pH_F / #G_pH_A;" in scl
    assert "#Decoupler_A11 := 1.0 + #Coupling_pH_F * #Coupling_pH_F" in scl
    assert "#Decoupler_Normal_Det := #Decoupler_A11 * #Decoupler_A22" in scl
    assert "#Decoupler_Weight_State := #Decoupler_Weight_State + 0.10 * #CycleTime" in scl
    assert 'Delta_q_f_Out => "DB1".Delta_q_f' in scl


def test_disabled_decoupler_preserves_independent_pid_corrections():
    scl = SCL_PATH.read_text(encoding="utf-8")
    assert "#Decoupled_q_f_Correction := #Direct_q_f_Correction;" in scl
    assert "#Decoupled_q_a_Correction := #Direct_q_a_Correction;" in scl
    assert "ELSE\n      #q_f_correction := #Direct_q_f_Correction;" in scl
    assert "#q_a_correction := #Direct_q_a_Correction;" in scl


def test_manual_mode_publishes_state_and_uses_direct_flow_commands():
    scl = SCL_PATH.read_text(encoding="utf-8")
    lad = MODE_INTERLOCK_LAD_PATH.read_text(encoding="utf-8-sig")
    assert 'Contact( "DB1".Manual_Mode )\n            Coil( "DB1".Manual_Active )' in lad
    assert 'Contact( "DB1".Manual_Active )\n            Coil( "DB1".Manual_PumpValve_Enable )' in lad
    assert 'in := "DB1".Manual_q_f_Set,\n                out1 => "DB1".Manual_q_f_Selected' in lad
    assert 'in := "DB1".Manual_q_a_Set,\n                out1 => "DB1".Manual_q_a_Selected' in lad
    assert 'IF #Mode_Manual THEN' in scl
    assert '"DB1".q_f_cmd := "DB1".Manual_q_f_Selected;' in scl
    assert '"DB1".q_a_cmd := "DB1".Manual_q_a_Selected;' in scl
    assert '"DB1".q_n_cmd := "DB1".Manual_q_n_Set;' in scl
    assert '"DB1".q_p_cmd := "DB1".Manual_q_p_Set;' in scl
    assert '"DB1".q_k_cmd := "DB1".Manual_q_k_Set;' in scl


def _solve_normalized_decoupler(c12, c21, v_ec, v_ph, regularization=0.0):
    a11 = 1.0 + c21 * c21 + regularization
    a12 = c12 + c21
    a22 = 1.0 + c12 * c12 + regularization
    b1 = v_ec + c21 * v_ph
    b2 = c12 * v_ec + v_ph
    determinant = a11 * a22 - a12 * a12
    return (
        (a22 * b1 - a12 * b2) / determinant,
        (-a12 * b1 + a11 * b2) / determinant,
    )


def test_normalized_decoupler_recovers_virtual_pid_requests():
    direct = (0.8, 0.35)
    assert _solve_normalized_decoupler(0.0, 0.0, *direct) == direct

    c12, c21 = 0.20, -0.10
    delta_f, delta_a = _solve_normalized_decoupler(c12, c21, *direct)
    assert abs(delta_f + c12 * delta_a - direct[0]) < 1e-12
    assert abs(c21 * delta_f + delta_a - direct[1]) < 1e-12


def test_regularization_keeps_near_singular_decoupler_finite():
    delta_f, delta_a = _solve_normalized_decoupler(0.999, 0.999, 0.8, 0.35, 0.01)
    assert abs(delta_f) < 100.0
    assert abs(delta_a) < 100.0
