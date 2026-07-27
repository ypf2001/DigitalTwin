from pathlib import Path

from plc_openness_v21.examples.add_stage_controls_main_overview import (
    make_auto_source_status,
)


def test_auto_source_control_is_read_only_status():
    source = Path(
        "plc_openness_v21/examples/add_stage_controls_main_overview.py"
    ).read_text(encoding="utf-8")

    assert make_auto_source_status is not None
    assert 'set_attr(item, "Enabled", "false")' in source
    assert 'dyn.text = \'"DB1.SAC_Enable"\'' in source
    assert 'set_text(item, "本地模式", "TextOff")' in source
    assert 'set_text(item, "联网模式", "TextOn")' in source
    assert '"DB1.Stage_Auto_SP_Enable"' not in source
