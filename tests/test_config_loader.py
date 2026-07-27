from pathlib import Path

from config_loader import load_config, reload_config


def test_load_config_cache_is_path_specific(tmp_path: Path):
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    first.write_text("env:\n  dt_min: 5\n", encoding="utf-8")
    second.write_text("env:\n  dt_min: 15\n", encoding="utf-8")

    cfg_first = reload_config(str(first))
    cfg_second = load_config(str(second))

    assert cfg_first.env()["dt_min"] == 5
    assert cfg_second.env()["dt_min"] == 15
    assert load_config(str(first)) is cfg_first


def test_active_calibration_profile_deep_merges(tmp_path: Path, monkeypatch):
    overlay = tmp_path / "field.yaml"
    overlay.write_text(
        "calibration:\n  id: test-field\nsoil_v2:\n  forcing:\n    et_scale: 1.23\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DT_CALIBRATION_PROFILE", str(overlay))
    cfg = reload_config()

    assert cfg.calibration()["id"] == "test-field"
    assert cfg.calibration()["active_profile"] == str(overlay.resolve())
    assert cfg.soil_v2()["forcing"]["et_scale"] == 1.23
    assert "irrigation_efficiency" in cfg.soil_v2()["forcing"]
    assert len(cfg.soil_v2()["profile"]["layer_thickness_mm"]) == 4

    monkeypatch.delenv("DT_CALIBRATION_PROFILE")
    reload_config()


def test_explicit_file_load_ignores_active_profile(tmp_path: Path, monkeypatch):
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "field.yaml"
    base.write_text("env:\n  dt_min: 7\n", encoding="utf-8")
    overlay.write_text("env:\n  dt_min: 99\n", encoding="utf-8")
    monkeypatch.setenv("DT_CALIBRATION_PROFILE", str(overlay))

    assert reload_config(str(base)).env()["dt_min"] == 7
    monkeypatch.delenv("DT_CALIBRATION_PROFILE")
    reload_config()
