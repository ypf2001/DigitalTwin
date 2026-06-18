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
