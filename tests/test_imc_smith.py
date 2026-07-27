import math

from digital_twin_env import DigitalTwinEnv
from plc_control.imc_smith import (
    FOPDTModel,
    PHPulseBandController,
    SmithPIController,
    acid_ec_feedforward,
    tune_imc_pi,
)


def test_imc_tuning_uses_process_sign_and_positive_integral_time():
    direct = tune_imc_pi(FOPDTModel(gain=0.5, tau_s=100.0, delay_s=20.0), 80.0)
    reverse = tune_imc_pi(FOPDTModel(gain=-0.5, tau_s=100.0, delay_s=20.0), 80.0)

    assert direct.kp > 0.0
    assert reverse.kp < 0.0
    assert direct.integral_time_s == 110.0
    assert math.isclose(direct.ki_per_s, direct.kp / direct.integral_time_s)


def test_smith_controller_is_bounded_and_reports_prediction():
    controller = SmithPIController(
        FOPDTModel(gain=1.0, tau_s=60.0, delay_s=20.0),
        dt_s=5.0,
        lambda_s=60.0,
        output_min=0.0,
        output_max=2.0,
    )

    results = [controller.step(setpoint=1.0, measurement=0.0) for _ in range(10)]

    assert all(0.0 <= item.output <= 2.0 for item in results)
    assert all(math.isfinite(item.predicted_output) for item in results)


def test_ph_band_only_acidifies_above_upper_limit_and_rejects_after_limit():
    controller = PHPulseBandController(
        lower=5.8,
        upper=6.5,
        hard_low=5.5,
        pulse_on_s=5.0,
        pulse_off_s=30.0,
        maximum_pulses=2,
    )

    first = controller.step(6.8, 1.0)
    in_band = controller.step(6.2, 40.0)
    second = controller.step(6.8, 1.0)
    rejected = controller.step(6.8, 40.0)
    low = PHPulseBandController().step(5.4, 1.0)

    assert first.acid_pulse and first.acid_duty == 1.0
    assert in_band.acid_duty == 0.0
    assert second.acid_pulse
    assert rejected.reject_batch
    assert low.flush_requested and low.reject_batch and low.acid_duty == 0.0


def test_digital_twin_coarse_pulse_recovers_without_locking_future_batches():
    env = DigitalTwinEnv(dt_min=5.0, ep_len_days=2.0, seed=7)
    env.reset()
    daytime = []
    for _ in range(100):
        _, _, _, info = env.step([1.0, 0.0])
        if not info["is_night"]:
            daytime.append(info)

    assert any(item["ph_acid_pulse"] for item in daytime)
    assert any(item["q_f"] > 0.0 for item in daytime)
    assert not any(item["ph_batch_reject"] for item in daytime[1:])


def test_acid_ec_feedforward_reduces_only_the_fertilizer_ec_command():
    corrected = acid_ec_feedforward(1.5, 0.5, 10.0, 2.0, ec_min=0.7)
    assert math.isclose(corrected, 1.4)
