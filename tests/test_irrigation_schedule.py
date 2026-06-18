import numpy as np

from irrigation_schedule import get_irrigation_schedule, normalize_obs


def test_schedule_totals():
    schedule = get_irrigation_schedule()
    t1_total_mm = sum(event.t1_mm for event in schedule)
    t2_total_mm = sum(event.t2_mm for event in schedule)

    assert abs(t1_total_mm - 180.0) < 1e-6
    assert abs(t2_total_mm - 180.0) < 1e-6


def test_normalize_obs_range():
    obs = np.zeros(23, dtype=np.float32)
    norm = normalize_obs(obs)

    assert norm.shape == (23,)
    assert np.all(norm >= -1.0)
    assert np.all(norm <= 1.0)
