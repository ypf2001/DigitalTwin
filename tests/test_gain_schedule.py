from pathlib import Path

import yaml

from plc_client import PLCClient
from plc_control.gain_schedule import identify_local_gain, select_gain_point
from plc_control.ab_validation import evaluate_ab_summary


def _rows():
    rows = []
    commands = [
        ("baseline", 2.0, 0.4),
        ("fertilizer_pos", 2.5, 0.4),
        ("recovery_1", 2.0, 0.4),
        ("fertilizer_neg", 1.5, 0.4),
        ("recovery_2", 2.0, 0.4),
        ("acid_pos", 2.0, 0.6),
        ("recovery_3", 2.0, 0.4),
        ("acid_neg", 2.0, 0.2),
    ]
    previous = commands[0][1:]
    timestamp = 0.0
    for name, q_f, q_a in commands:
        for sample in range(10):
            active_q_f = previous[0] if sample == 0 and name != "baseline" else q_f
            active_q_a = previous[1] if sample == 0 and name != "baseline" else q_a
            rows.append({
                "stage": "MID", "operating_point": "medium", "step_name": name,
                "timestamp_s": timestamp, "ec_set": 1.5, "ph_set": 5.9,
                "q_f_baseline": 2.0, "q_a_baseline": 0.4,
                "q_f_cmd": active_q_f, "q_a_cmd": active_q_a,
                "ec": 0.5 * active_q_f + 0.2 * active_q_a,
                "ph": 7.0 - 0.3 * active_q_f - 0.8 * active_q_a,
            })
            timestamp += 1.0
        previous = (q_f, q_a)
    return rows


def test_identify_local_gain_uses_positive_and_negative_steps():
    point = identify_local_gain(_rows(), "MID", "medium")
    assert point["valid"]
    assert abs(point["gains"]["g_ec_f"] - 0.5) < 1e-9
    assert abs(point["gains"]["g_ec_a"] - 0.2) < 1e-9
    assert abs(point["gains"]["g_ph_f"] + 0.3) < 1e-9
    assert abs(point["gains"]["g_ph_a"] + 0.8) < 1e-9


def test_select_gain_point_ignores_disabled_or_invalid_schedule():
    point = identify_local_gain(_rows(), "MID", "medium")
    schedule = {
        "enabled": True,
        "selection": {"ec_scale": 0.5, "ph_scale": 0.5, "q_f_scale": 5.0, "q_a_scale": 2.0},
        "stages": {"MID": {"points": [point]}},
    }
    assert select_gain_point(schedule, "MID", 1.5, 5.9, 2.0, 0.4)["id"] == "medium"
    schedule["enabled"] = False
    assert select_gain_point(schedule, "MID", 1.5, 5.9, 2.0, 0.4) is None


def test_write_active_gain_matrix_never_enables_decoupler():
    config = yaml.safe_load((Path(__file__).parents[1] / "config" / "simulation.yaml").read_text(encoding="utf-8"))
    client = PLCClient.__new__(PLCClient)
    client.db_number = 1
    client.addr_map = config["plc"]["addresses"]
    client._client = type("MemoryPLC", (), {
        "memory": bytearray(528),
        "db_read": lambda self, db, start, size: self.memory[start:start + size],
        "db_write": lambda self, db, start, data: self.memory.__setitem__(slice(start, start + len(data)), data),
    })()
    client._ensure_connected = lambda: None
    point = identify_local_gain(_rows(), "MID", "medium")
    assert client.write_active_gain_matrix(point)
    assert client.read_control_parameters()["flat"]["Decoupler_Enable"] is False


def test_ab_acceptance_requires_both_disturbance_directions_to_improve():
    summary = {
        "weights": [
            {"weight": 0.0, "disturbance": "ec", "ec_mae": 0.10, "ph_mae": 0.10,
             "cross_coupling_peak": 0.10, "q_f_saturation_count": 0,
             "q_a_saturation_count": 0, "alarm_count": 0, "communication_failures": 0},
            {"weight": 0.0, "disturbance": "ph", "ec_mae": 0.10, "ph_mae": 0.10,
             "cross_coupling_peak": 0.10, "q_f_saturation_count": 0,
             "q_a_saturation_count": 0, "alarm_count": 0, "communication_failures": 0},
            {"weight": 0.1, "disturbance": "ec", "ec_mae": 0.10, "ph_mae": 0.10,
             "cross_coupling_peak": 0.08, "q_f_saturation_count": 0,
             "q_a_saturation_count": 0, "alarm_count": 0, "communication_failures": 0},
            {"weight": 0.1, "disturbance": "ph", "ec_mae": 0.10, "ph_mae": 0.10,
             "cross_coupling_peak": 0.10, "q_f_saturation_count": 0,
             "q_a_saturation_count": 0, "alarm_count": 0, "communication_failures": 0},
        ]
    }
    verdict = evaluate_ab_summary(summary, {
        "baseline_weight": 0.0,
        "candidate_weights": [0.1],
        "require_all_disturbances": True,
        "min_cross_coupling_reduction_fraction": 0.10,
        "max_ec_mae_degradation_abs": 0.01,
        "max_ph_mae_degradation_abs": 0.01,
    })
    assert verdict["passed"] is False
