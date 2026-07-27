from plc_control.ab_validation import summarize_ab_rows


def _case(weight: float, disturbance: str, cross_offset: float, cross_response: float) -> list[dict]:
    rows = []
    for time_s in (0.0, 10.0, 20.0, 30.0):
        stepped = time_s >= 20.0
        ec_set = 1.65 if disturbance == "ec" and stepped else 1.5
        ph_set = 6.05 if disturbance == "ph" and stepped else 5.9
        ec_actual = 1.5 + cross_offset
        ph_actual = 5.9 + cross_offset
        if stepped:
            if disturbance == "ec":
                ph_actual += cross_response
            else:
                ec_actual += cross_response
        rows.append({
            "weight": weight,
            "disturbance": disturbance,
            "time_s": time_s,
            "ec_set": ec_set,
            "ph_set": ph_set,
            "ec_actual": ec_actual,
            "ph_actual": ph_actual,
            "q_f_cmd": 1.0,
            "q_a_cmd": 0.5,
            "q_f_limited": False,
            "q_a_limited": False,
            "q_f_saturated": False,
            "q_a_saturated": False,
            "alarm": False,
            "remote_comms_ok": True,
            "setpoint_protection": False,
            "decoupler_enable": weight > 0.0,
            "decoupler_valid": True,
        })
    return rows


def test_cross_coupling_uses_pre_step_actual_baseline_not_setpoint_error():
    rows = _case(0.0, "ec", cross_offset=0.08, cross_response=0.03)
    rows += _case(0.0, "ph", cross_offset=0.08, cross_response=0.04)

    summary = summarize_ab_rows(rows, baseline_window_s=20.0)
    by_disturbance = {row["disturbance"]: row for row in summary["weights"]}

    assert abs(by_disturbance["ec"]["cross_coupling_peak"] - 0.03) < 1e-12
    assert abs(by_disturbance["ph"]["cross_coupling_peak"] - 0.04) < 1e-12
    assert by_disturbance["ec"]["cross_coupling_metric"] == "pre_step_baseline_delta_peak"
    assert by_disturbance["ec"]["baseline_samples"] == 2


def test_summary_accepts_csv_string_values():
    rows = _case(0.1, "ec", cross_offset=0.02, cross_response=0.01)
    rows += _case(0.1, "ph", cross_offset=0.02, cross_response=0.01)
    string_rows = [{key: str(value) for key, value in row.items()} for row in rows]

    summary = summarize_ab_rows(string_rows, baseline_window_s=20.0)

    assert len(summary["weights"]) == 2
    assert summary["decoupler_enabled_during_test"] is True
    assert all(row["communication_failures"] == 0 for row in summary["weights"])
