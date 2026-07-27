import math

from plc_control.constrained_ab import evaluate_constrained_ab
from plc_control.gain_schedule import aggregate_gain_repetitions
from plc_control.mimo_fopdt import MIMOFOPDTParameters, MIMOFOPDTPlant


def _estimate(scale=1.0):
    gains = {
        "g_ec_f": 0.4 * scale,
        "g_ec_a": 0.1 * scale,
        "g_ph_f": -0.12 * scale,
        "g_ph_a": -0.55 * scale,
    }
    responses = {str(index): {"signal_to_noise": 10.0} for index in range(8)}
    return {
        "gains": gains, "delay_s": 180.0, "tau_s": 300.0,
        "condition_number": 2.0, "valid": True, "quality_ok": True,
        "responses": responses,
    }


def test_mimo_fopdt_preserves_cross_channel_signs():
    plant = MIMOFOPDTPlant(
        MIMOFOPDTParameters(0.4, 0.1, -0.12, -0.55, 0.0, 10.0, 10.0),
        dt_s=1.0,
    )
    plant.reset(4.0, 0.8, 1.5, 6.2)
    ec, ph = 1.5, 6.2
    for _ in range(100):
        ec, ph = plant.step(4.0, 1.0)
    assert ec > 1.5
    assert ph < 6.2


def test_e3_aggregate_requires_three_stable_repetitions():
    result = aggregate_gain_repetitions([_estimate(0.99), _estimate(1.0), _estimate(1.01)])
    assert result["valid"] is True
    assert result["repetitions"] == 3
    assert result["condition_number"] < 10.0
    assert all(stat["cv"] < 0.20 for stat in result["gain_stats"].values())


def _metric(weight, disturbance, repetition, *, cross=0.10, iae=10.0, recovery=120.0):
    return {
        "point": "medium", "weight": weight, "disturbance": disturbance,
        "repetition": repetition, "ec_cross_peak": cross,
        "ec_mae": 0.02, "ec_tail_mae": 0.01, "ec_iae": iae,
        "ph_recovery_s": recovery, "ph_min": 5.9,
        "ph_band_occupancy_after_recovery": 1.0,
        "flush_requested": disturbance == "ph_low", "acid_while_low": False,
        "batch_reject_count": 0, "saturation_count": 0,
        "alarm_count": 0, "communication_failure_count": 0,
    }


def test_e4_selects_lowest_passing_weight():
    metrics = []
    for repetition in range(1, 4):
        for disturbance in ("ph_high", "ec_step", "ph_low"):
            metrics.append(_metric(0.0, disturbance, repetition))
            metrics.append(_metric(
                0.1, disturbance, repetition,
                cross=0.07 if disturbance == "ph_high" else 0.10,
            ))
            metrics.append(_metric(
                0.25, disturbance, repetition,
                cross=0.06 if disturbance == "ph_high" else 0.10,
            ))
    criteria = {
        "baseline_weight": 0.0, "candidate_weights": [0.1, 0.25], "repetitions": 3,
        "min_cross_coupling_reduction_fraction": 0.20,
        "max_main_loop_iae_degradation_fraction": 0.10,
        "max_ph_recovery_degradation_fraction": 0.10,
        "ph_band_low": 5.8, "ec_mae_max": 0.03, "ec_tail_mae_max": 0.03,
        "ph_band_occupancy_min": 0.95,
    }
    verdict = evaluate_constrained_ab(metrics, criteria)
    assert verdict["passed"] is True
    assert math.isclose(verdict["selected_weight"], 0.1)


def test_plc_source_contains_standalone_constrained_decoupling():
    source = open("plc/xiaweiji/src/xiaweiji.scl", encoding="utf-8").read()
    assert "Gain_Low_G_EC_F : Real" in source
    assert "Gain_Point_Override : Int" in source
    assert '"DB1".Gain_Schedule_Valid :=' in source
    assert "#Acid_EC_Compensation := -(#G_EC_A / #G_EC_F) * #pH_Pulse_Demand;" in source
    assert 'AND ("DB1".E4_Approved OR ("DB1".E4_Test_Enable' in source
    assert "E4_Compressed_Time_Enable : Bool" in source
    assert '#Control_CycleTime := "DB1".E4_Sim_Step_s;' in source
    assert "#q_f_feedforward := #IMC_q_f_Operating" in source
    assert 'IMC_EC_Operating_SP := "DB1".Active_Gain_EC_SP' in source
