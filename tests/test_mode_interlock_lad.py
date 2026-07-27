from plc_openness_v21.examples.create_mode_interlock_lad_xml import (
    FLG_NS,
    flgnet_manual_pump_valve_enable,
    q,
)


def test_local_manual_enable_does_not_depend_on_remote_comms():
    network = flgnet_manual_pump_valve_enable()
    component_names = [
        component.attrib["Name"]
        for component in network.findall(f".//{q(FLG_NS, 'Component')}")
    ]
    part_names = [
        part.attrib["Name"]
        for part in network.findall(f".//{q(FLG_NS, 'Part')}")
    ]

    assert component_names == ["DB1", "Manual_Active", "DB1", "Manual_PumpValve_Enable"]
    assert "Comm_Normal" not in component_names
    assert part_names == ["Contact", "Coil"]
