import numpy as np

from config_loader import reload_config
from digital_twin_gym_env import DigitalTwinGymEnv


def test_default_timestep_resolves_pipe_delay():
    cfg = reload_config()

    assert cfg.env()["dt_min"] < cfg.pipe()["tau"]


def test_gym_env_step_accepts_fixed_strategy_action():
    env = DigitalTwinGymEnv(growth_stage="MID", obs_noise_std=0.0, ep_len_days=0.05)
    obs, info = env.reset()
    action = np.array(reload_config().action()["fixed_strategy"], dtype=np.float32)

    assert obs.shape == env.observation_space.shape
    assert np.all(obs >= -1.0)
    assert np.all(obs <= 1.0)
    assert env.action_space.contains(action)

    obs, reward, terminated, truncated, step_info = env.step(action)

    assert obs.shape == env.observation_space.shape
    assert np.isfinite(reward)
    assert not truncated
    assert "ec_set" in step_info
    assert "ph_set" in step_info
    assert "q_f" in step_info
    assert "q_a" in step_info
    assert isinstance(terminated, bool)
