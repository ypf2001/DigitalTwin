from plc_client import PLCClient


class SizeLimitedClient:
    def __init__(self, max_end: int):
        self.max_end = max_end
        self.calls = []

    def db_read(self, db_number: int, start: int, size: int):
        self.calls.append((db_number, start, size))
        if start + size > self.max_end:
            raise RuntimeError("CLI : function refused by CPU (Unknown error)")
        return bytearray(size)


def make_plc(max_end: int) -> PLCClient:
    plc = PLCClient.__new__(PLCClient)
    plc.db_number = 1
    plc.addr_map = {
        "Remote_Comms_OK": {"offset": 20, "bit": 0, "type": "bool", "bytes": 1},
        "q_f_cmd": {"offset": 24, "type": "real", "bytes": 4},
        "Kp_EC_Effective": {"offset": 312, "type": "real", "bytes": 4},
        "Kp_pH_Effective": {"offset": 324, "type": "real", "bytes": 4},
        "Adaptive_PID_Active": {"offset": 396, "bit": 4, "type": "bool", "bytes": 1},
    }
    plc._client = SizeLimitedClient(max_end)
    plc._ensure_connected = lambda: None
    return plc


def test_read_state_falls_back_when_plcsim_still_has_old_db1():
    plc = make_plc(max_end=312)

    state = plc.read_state()

    assert state is not None
    assert state["adaptive_schema_available"] is False
    assert "Remote_Comms_OK" in state
    assert "q_f_cmd" in state
    assert "Kp_EC_Effective" not in state
    assert len(plc._client.calls) == 2
    assert plc._client.calls[0][1] + plc._client.calls[0][2] > 312
    assert plc._client.calls[1][1] + plc._client.calls[1][2] <= 312


def test_read_state_reports_new_adaptive_schema():
    plc = make_plc(max_end=397)

    state = plc.read_state()

    assert state is not None
    assert state["adaptive_schema_available"] is True
    assert "Kp_EC_Effective" in state
    assert "Adaptive_PID_Active" in state
    assert len(plc._client.calls) == 1


def make_water_plc(max_end: int) -> PLCClient:
    plc = make_plc(max_end)
    plc.addr_map.update({
        "Qw_Set": {"offset": 404, "type": "real", "bytes": 4},
        "Qw_Actual": {"offset": 408, "type": "real", "bytes": 4},
        "Water_Pump_Run_CMD": {"offset": 436, "bit": 0, "type": "bool", "bytes": 1},
        "Water_Flow_OK": {"offset": 436, "bit": 4, "type": "bool", "bytes": 1},
        "Water_Pump_Alarm": {"offset": 442, "bit": 0, "type": "bool", "bytes": 1},
    })
    return plc


def test_read_state_keeps_adaptive_fields_when_water_extension_is_not_downloaded():
    plc = make_water_plc(max_end=397)

    state = plc.read_state()

    assert state is not None
    assert state["adaptive_schema_available"] is True
    assert state["water_schema_available"] is False
    assert "Kp_EC_Effective" in state
    assert "Qw_Actual" not in state
    assert len(plc._client.calls) == 2


def test_read_state_reports_water_extension_when_downloaded():
    plc = make_water_plc(max_end=443)

    state = plc.read_state()

    assert state is not None
    assert state["adaptive_schema_available"] is True
    assert state["water_schema_available"] is True
    assert "Qw_Actual" in state
    assert "Water_Flow_OK" in state
    assert len(plc._client.calls) == 1


def test_read_state_reports_irrigation_batch_extension_when_downloaded():
    plc = make_water_plc(max_end=463)
    plc.addr_map.update({
        "Pre_Flush_Ratio": {"offset": 444, "type": "real", "bytes": 4},
        "Post_Flush_Ratio": {"offset": 448, "type": "real", "bytes": 4},
        "Water_Batch_Phase": {"offset": 460, "type": "int", "bytes": 2},
        "Batch_Fertigation_Active": {"offset": 462, "bit": 0, "type": "bool", "bytes": 1},
    })

    state = plc.read_state()

    assert state is not None
    assert state["water_schema_available"] is True
    assert state["water_batch_schema_available"] is True
    assert "Water_Batch_Phase" in state
    assert len(plc._client.calls) == 1
