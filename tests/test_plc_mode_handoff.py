from plc_client import PLCClient
from plc_gym_env import PLCGymEnv


class FakePLC:
    def __init__(self):
        self.mode_state = {
            "Manual_Mode": False,
            "Auto_Mode": True,
            "Manual_Active": False,
            "Auto_Active": True,
        }
        self.calls = []

    def read_control_mode(self):
        if self.mode_state is None:
            return None
        return self.mode_state.copy()

    def write_setpoints(self, ec_set, ph_set, ec_actual, ph_actual, sac_enable=True):
        self.calls.append(("targets", ec_set, ph_set, ec_actual, ph_actual, sac_enable))
        return True

    def write_feedback(self, ec_actual, ph_actual, sac_enable):
        self.calls.append(("feedback", ec_actual, ph_actual, sac_enable))
        return True


def make_env(plc):
    env = object.__new__(PLCGymEnv)
    env.plc = plc
    env.plc_enabled = True
    env._last_plc_state = {"Manual_Active": False, "Auto_Active": True}
    return env


def test_supervisory_targets_pause_in_manual_and_resume_in_auto():
    plc = FakePLC()
    env = make_env(plc)

    assert env._sync_plc_inputs(1.1, 6.1, 0.9, 6.2)

    plc.mode_state.update(
        Manual_Mode=True,
        Auto_Mode=False,
        Manual_Active=True,
        Auto_Active=False,
    )
    assert env._sync_plc_inputs(1.5, 5.9, 1.0, 6.0)

    plc.mode_state.update(
        Manual_Mode=False,
        Auto_Mode=True,
        Manual_Active=False,
        Auto_Active=True,
    )
    assert env._sync_plc_inputs(1.0, 6.1, 1.2, 6.0)

    assert plc.calls == [
        ("targets", 1.1, 6.1, 0.9, 6.2, True),
        ("feedback", 1.0, 6.0, False),
        ("targets", 1.0, 6.1, 1.2, 6.0, True),
    ]


def test_failed_mode_read_keeps_last_confirmed_manual_state():
    plc = FakePLC()
    env = make_env(plc)
    env._last_plc_state["Manual_Active"] = True
    plc.mode_state = None

    assert env._sync_plc_inputs(1.5, 5.9, 1.0, 6.0)
    assert plc.calls == [("feedback", 1.0, 6.0, False)]


def test_reset_or_close_does_not_overwrite_targets_during_manual():
    plc = FakePLC()
    plc.mode_state.update(Manual_Active=True, Auto_Active=False)
    env = make_env(plc)

    assert env._sync_plc_inputs(0.8, 7.0, 0.0, 7.0, automatic_enable=False)
    assert plc.calls == [("feedback", 0.0, 7.0, False)]


def test_feedback_only_write_does_not_touch_automatic_targets():
    client = object.__new__(PLCClient)
    client.addr_map = {"SAC_Enable": {}}
    client._heartbeat = 41
    client._connected = True
    writes = []
    client._ensure_connected = lambda: None
    client._write_bool = lambda name, value: writes.append((name, value))
    client._write_real = lambda name, value: writes.append((name, value))
    client._write_int = lambda name, value: writes.append((name, value))

    assert client.write_feedback(0.9, 6.2, sac_enable=False)

    assert writes == [
        ("SAC_Enable", False),
        ("EC_Actual", 0.9),
        ("pH_Actual", 6.2),
        ("Remote_Heartbeat", 42),
    ]
    assert all(name not in {"EC_Set_SP", "pH_Set_SP"} for name, _ in writes)
