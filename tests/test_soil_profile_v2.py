import numpy as np

from soil_profile_v2 import LayeredSoilProfile, sample_soil_config


def test_reset_returns_configured_finite_profiles():
    soil = LayeredSoilProfile()
    info = soil.diagnostics()

    assert len(info["theta_profile"]) == 4
    assert len(info["ec_profile"]) == 4
    assert len(info["n_profile"]) == 4
    assert np.all(np.isfinite(info["theta_profile"]))
    assert info["parameter_status"] == "literature_placeholder"
    assert info["n_target"] > 0.0
    assert info["p_target"] > 0.0
    assert info["k_target"] > 0.0


def test_legacy_ec_soil_setter_updates_profile_and_salt_mass():
    soil = LayeredSoilProfile()

    soil.ec_soil = 0.78

    assert soil.ec_soil == 0.78
    assert np.allclose(soil.ec_profile, 0.78)
    assert np.allclose(soil.salt_mass, soil.ec_profile * soil.water_mm)
    assert np.allclose(soil.diagnostics()["ec_profile"], 0.78)



def test_irrigation_moves_water_and_conserves_mass():
    soil = LayeredSoilProfile()
    before = soil.theta_profile.copy()

    soil.step(I=20.0, EC_in=1.2, ET=0.0, dt_hours=1.0, ph_in=6.0)
    info = soil.diagnostics()

    assert soil.theta_profile[0] > before[0]
    assert soil.theta_profile[1] > before[1]
    assert info["drainage_mm"] >= 0.0
    assert abs(info["water_balance_error_mm"]) < 1e-8
    assert abs(info["salt_balance_error"]) < 1e-8


def test_acid_irrigation_is_buffered_and_fertilizer_adds_npk():
    soil = LayeredSoilProfile(area_ha=1.0)
    ph_before = soil.ph_soil
    nutrient_before = np.array([soil.n_actual, soil.p_actual, soil.k_actual])

    for _ in range(24):
        soil.step(
            I=2.0, EC_in=1.1, ET=0.2, dt_hours=1.0,
            ph_in=5.5, q_f_l_min=8.0, stage="bulking",
        )

    nutrient_after = np.array([soil.n_actual, soil.p_actual, soil.k_actual])
    assert 5.5 < soil.ph_soil < ph_before
    assert np.all(nutrient_after > nutrient_before)
    assert np.all(soil.theta_profile >= soil.theta_wp_profile)
    assert np.all(soil.theta_profile <= soil.theta_sat_profile)
    for value in soil.diagnostics()["nutrient_balance_error_mg_m2"].values():
        assert abs(value) < 1e-6
    info = soil.diagnostics()
    assert abs(info["q_n_cmd"] + info["q_p_cmd"] + info["q_k_cmd"] - 8.0) < 1e-9


def test_long_run_remains_finite_and_nonnegative():
    soil = LayeredSoilProfile()
    soil.set_growth_stage("starch_accumulation", 400.0)
    for hour in range(240):
        daytime = 6 <= hour % 24 < 20
        soil.step(
            I=1.0 if daytime else 0.0,
            EC_in=1.3,
            ET=0.25 if daytime else 0.0,
            dt_hours=1.0,
            ph_in=6.1,
            q_f_l_min=3.0 if daytime else 0.0,
            stage="starch_accumulation",
        )
    info = soil.diagnostics()
    for key in ("theta_profile", "ec_profile", "ph_profile",
                "n_profile", "p_profile", "k_profile"):
        values = np.asarray(info[key])
        assert np.all(np.isfinite(values))
        assert np.all(values >= 0.0)


def test_domain_randomization_stays_in_range_and_does_not_mutate_source():
    base = {
        "profile": {"k_sat_mm_h": [10.0, 5.0]},
        "forcing": {"et_scale": 1.0},
        "domain_randomization": {
            "relative_range": {
                "profile.k_sat_mm_h": 0.20,
                "forcing.et_scale": 0.10,
            }
        },
    }
    sampled = sample_soil_config(base, np.random.RandomState(123))

    assert base["profile"]["k_sat_mm_h"] == [10.0, 5.0]
    assert base["forcing"]["et_scale"] == 1.0
    ratio_top = sampled["profile"]["k_sat_mm_h"][0] / 10.0
    ratio_bottom = sampled["profile"]["k_sat_mm_h"][1] / 5.0
    assert 0.80 <= ratio_top <= 1.20
    assert ratio_top == ratio_bottom
    assert 0.90 <= sampled["forcing"]["et_scale"] <= 1.10
