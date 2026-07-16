import numpy as np

from digital_twin_env import DigitalTwinEnv
from water_pump import WaterPump


def test_water_pump_reaches_flow_and_reports_hydraulic_state():
    pump = WaterPump(q_set_l_min=120.0)
    pump.set_command(enabled=True, q_set_l_min=120.0, reset_volume=True)

    state = pump.step(1.0)

    assert 0.0 < state.q_actual_l_min <= 120.0
    assert state.running
    assert state.flow_ok
    assert state.pressure_actual_bar > 0.0
    assert state.speed_percent > 0.0
    assert state.volume_l > 0.0


def test_target_volume_completes_and_stops_new_dosing_permission():
    pump = WaterPump(q_set_l_min=100.0)
    pump.set_command(
        enabled=True,
        q_set_l_min=100.0,
        target_volume_l=50.0,
        reset_volume=True,
    )

    state = pump.step(1.0)

    assert state.volume_complete
    assert not state.enabled
    assert not state.flow_ok


def test_volume_bounded_batch_has_pre_fertigation_and_post_flush_sections():
    pump = WaterPump(q_set_l_min=100.0)
    pump.set_command(
        enabled=True,
        q_set_l_min=100.0,
        target_volume_l=100.0,
        pre_flush_ratio=0.10,
        post_flush_ratio=0.20,
        reset_volume=True,
    )

    state = pump.state()
    assert state.batch_phase == "pre_flush"
    assert not state.fertigation_active
    assert state.pre_flush_volume_l == 10.0
    assert state.fertigation_end_volume_l == 80.0

    pump.volume_l = 30.0
    pump.flow_ok = True
    state = pump.state()
    assert state.batch_phase == "fertigating"
    assert state.fertigation_active

    pump.volume_l = 90.0
    state = pump.state()
    assert state.batch_phase == "post_flush"
    assert not state.fertigation_active


def test_no_carrier_water_forces_fertilizer_and_acid_off():
    env = DigitalTwinEnv(obs_noise_std=0.0, ep_len_days=0.05)
    env.reset()
    env.set_irrigation_command(enabled=False)

    _, reward, _, info = env.step(np.array([1.5, 6.0], dtype=np.float32))

    assert np.isfinite(reward)
    assert info["q_w_actual"] == 0.0
    assert info["q_f"] == 0.0
    assert info["q_a"] == 0.0
    assert info["irrigation_mm_h"] == 0.0
    assert not info["water_flow_ok"]


def test_pre_and_post_flush_force_dosing_off_in_the_digital_twin():
    env = DigitalTwinEnv(obs_noise_std=0.0, ep_len_days=0.2)
    env.reset()
    env._time_min = 7.0 * 60.0
    env.set_irrigation_command(
        enabled=True,
        q_set_l_min=136.0,
        target_volume_l=10000.0,
        pre_flush_ratio=0.10,
        post_flush_ratio=0.20,
        reset_volume=True,
    )

    _, _, _, pre_info = env.step(np.array([1.5, 6.0], dtype=np.float32))
    assert pre_info["water_batch_phase"] == "pre_flush"
    assert pre_info["q_f"] == 0.0
    assert pre_info["q_a"] == 0.0

    _, _, _, fert_info = env.step(np.array([1.5, 6.0], dtype=np.float32))
    assert fert_info["water_batch_phase"] == "fertigating"
    assert fert_info["fertigation_active"]
    assert fert_info["q_f"] > 0.0

    env.water_pump.volume_l = 9000.0
    _, _, _, post_info = env.step(np.array([1.5, 6.0], dtype=np.float32))
    assert post_info["water_batch_phase"] == "post_flush"
    assert post_info["q_f"] == 0.0
    assert post_info["q_a"] == 0.0


def test_default_environment_uses_dynamic_measured_water_flow():
    env = DigitalTwinEnv(obs_noise_std=0.0, ep_len_days=0.05)
    env.reset()

    _, _, _, info = env.step(np.array([1.5, 6.0], dtype=np.float32))

    assert info["q_w_set"] == 136.0
    assert 0.0 < info["q_w_actual"] <= info["q_w_set"]
    assert info["water_flow_ok"]
    assert info["total_flow_Lmin"] == (
        info["q_w_actual"] + info["q_f"] + info["q_a"]
    )
