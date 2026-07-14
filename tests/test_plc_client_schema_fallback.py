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
