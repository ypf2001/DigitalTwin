from experiments.run_full_season_plc import (
    EC_PH_INTEGRAL_LIMIT,
    STAGE_SEQUENCE,
    _build_acceptance_metrics,
)


def good_rows():
    rows = []
    for stage in STAGE_SEQUENCE:
        for idx in range(12):
            q_f = 0.9
            rows.append({
                "stage": stage,
                "plc_ec_target": 1.2,
                "plc_ec_actual": 1.195 + (idx % 2) * 0.001,
                "plc_ph_target": 6.1,
                "plc_ph_actual": 6.095 + (idx % 2) * 0.001,
                "n_target": 1.0,
                "p_target": 0.8,
                "k_target": 1.2,
                "n_actual": 1.01,
                "p_actual": 0.792,
                "k_actual": 1.212,
                "npk_feedback_valid": True,
                "q_f_cmd": q_f,
                "q_n_cmd": 0.3,
                "q_p_cmd": 0.2,
                "q_k_cmd": 0.4,
                "npk_capacity_limited": False,
                "remote_comms_ok": True,
                "adaptive_schema_available": True,
                "adaptive_pid_active": True,
                "q_f_limited": False,
                "q_a_limited": False,
                "ec_pid_integral": 0.02,
                "ph_pid_integral": -0.01,
                "kp_ec_effective": 1.0 + idx * 0.01,
                "ki_ec_effective": 0.1,
                "kd_ec_effective": 0.01,
                "kp_ph_effective": 1.1,
                "ki_ph_effective": 0.11,
                "kd_ph_effective": 0.02,
            })
    return rows


def test_acceptance_metrics_pass_a_stable_coordinated_run():
    result = _build_acceptance_metrics(good_rows())

    assert result["pass"] is True
    assert result["checks"]["ec_steady_within_0_02"] is True
    assert result["checks"]["npk_steady_within_5_percent"] is True
    assert result["fertilizer_budget_error"]["max_abs"] < 1e-9
    assert result["effective_gain_ranges"]["kp_ec_effective"]["max"] > 1.0


def test_budget_tolerance_accepts_scan_jitter_but_rejects_real_gap():
    rows = good_rows()
    for row in rows:
        row["q_f_cmd"] = 0.895  # 0.005 absolute / about 0.6% snapshot jitter
    assert _build_acceptance_metrics(rows)["checks"]["fertilizer_budget_consistent"] is True

    for row in rows:
        row["q_f_cmd"] = 0.88  # 0.02 is a material allocation gap
    assert _build_acceptance_metrics(rows)["checks"]["fertilizer_budget_consistent"] is False


def test_acceptance_metrics_rejects_long_integral_saturation():
    rows = good_rows()
    for row in rows:
        row["ec_pid_integral"] = EC_PH_INTEGRAL_LIMIT
    result = _build_acceptance_metrics(rows)
    assert result["pass"] is False
    assert result["checks"]["no_long_integral_saturation"] is False

def test_acceptance_metrics_does_not_treat_old_limit_as_saturation():
    rows = good_rows()
    for row in rows:
        row["ec_pid_integral"] = 5.0
    result = _build_acceptance_metrics(rows)
    assert result["checks"]["no_long_integral_saturation"] is True


def test_acceptance_metrics_rejects_large_npk_error_and_missing_schema():
    rows = good_rows()
    for row in rows:
        row["n_actual"] = 1.2
        row["adaptive_schema_available"] = False

    result = _build_acceptance_metrics(rows)

    assert result["pass"] is False
    assert result["checks"]["npk_steady_within_5_percent"] is False
    assert result["checks"]["adaptive_schema_at_least_95_percent"] is False


def test_full_season_requires_downloaded_adaptive_db1():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "experiments" / "run_full_season_plc.py"
    ).read_text(encoding="utf-8")

    assert 'initial_state = plc.read_state()' in source
    assert 'initial_state.get("adaptive_schema_available", False)' in source
    assert 'DB1 is still the old schema' in source
