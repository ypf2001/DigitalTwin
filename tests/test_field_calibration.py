import copy
import csv
import sys

import yaml

from config_loader import load_config
from scripts import calibrate_field_model
from soil_profile_v2 import LayeredSoilProfile


def test_field_calibration_writes_versioned_profile(tmp_path, monkeypatch):
    csv_path = tmp_path / "field.csv"
    output_path = tmp_path / "profile.yaml"
    soil = LayeredSoilProfile(config=copy.deepcopy(load_config().soil_v2()))
    fields = ["dt_hours", "irrigation_mm_h", "ec_in_ds_m", "ph_in", "et_mm_h"]
    fields += [f"{kind}_l{layer}" for kind in ("theta", "ec", "ph") for layer in range(1, 5)]
    rows = []

    def snapshot(dt, irrigation, ec_in, ph_in, et):
        row = {
            "dt_hours": dt,
            "irrigation_mm_h": irrigation,
            "ec_in_ds_m": ec_in,
            "ph_in": ph_in,
            "et_mm_h": et,
        }
        for index in range(4):
            row[f"theta_l{index + 1}"] = soil.theta_profile[index]
            row[f"ec_l{index + 1}"] = soil.ec_profile[index]
            row[f"ph_l{index + 1}"] = soil.ph_profile[index]
        return row

    rows.append(snapshot(0.0, 0.0, 0.0, 7.0, 0.0))
    for step in range(1, 9):
        irrigation = 2.0 if step in (1, 2, 6) else 0.0
        ec_in = 1.3 if irrigation else 0.0
        ph_in = 6.3 if irrigation else 7.0
        et = 0.10
        soil.step(I=irrigation, EC_in=ec_in, ET=et, dt_hours=1.0, ph_in=ph_in, stage="bulking")
        rows.append(snapshot(1.0, irrigation, ec_in, ph_in, et))

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    monkeypatch.setattr(sys, "argv", [
        "calibrate_field_model.py", str(csv_path), "--trials", "10",
        "--output", str(output_path),
    ])
    assert calibrate_field_model.main() == 0

    profile = yaml.safe_load(output_path.read_text(encoding="utf-8"))
    assert profile["calibration"]["row_count"] == 9
    assert profile["soil_v2"]["parameter_status"] == "field_calibrated"
    assert profile["soil_v2"]["default_model"] == "layered_v2"
    assert profile["calibration"]["validation_metrics"]["theta_count"] > 0
    assert output_path.with_suffix(".report.json").is_file()
