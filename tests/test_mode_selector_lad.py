from itertools import product

from plc_openness_v21.examples.create_mode_selector_lad_xml import (
    INPUT_NAMES,
    NETWORK_SPECS,
    OUTPUT_NAMES,
)


def _evaluate(values: dict[str, bool]) -> dict[str, bool]:
    outputs: dict[str, bool] = {}
    for _, conditions, output_name in NETWORK_SPECS:
        outputs[output_name] = all(
            (not values[input_name]) if negated else values[input_name]
            for input_name, negated in conditions
        )
    return outputs


def test_mode_selector_covers_all_inputs_with_one_active_mode():
    for combination in product((False, True), repeat=len(INPUT_NAMES)):
        values = dict(zip(INPUT_NAMES, combination))
        outputs = _evaluate(values)

        assert tuple(outputs) == OUTPUT_NAMES
        assert sum(outputs.values()) == 1


def test_manual_mode_has_priority_over_all_automatic_commands():
    outputs = _evaluate(
        {
            "Emergency_Stop": False,
            "Manual_Mode": True,
            "Auto_Mode": True,
            "SAC_Enable": True,
            "Stage_Auto_SP_Enable": True,
        }
    )

    assert outputs["Mode_Manual"] is True
    assert all(not active for name, active in outputs.items() if name != "Mode_Manual")
