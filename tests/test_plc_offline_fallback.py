from pathlib import Path


SCL_PATH = Path(__file__).resolve().parents[1] / "plc" / "xiaweiji" / "src" / "xiaweiji.scl"


def source() -> str:
    return SCL_PATH.read_text(encoding="utf-8")


def test_remote_loss_falls_back_to_local_stage_mode():
    scl = source()

    assert '#Remote_Auto_Available := "DB1".SAC_Enable AND "DB1".Remote_Comms_OK;' in scl
    assert 'SAC_Enable := #Remote_Auto_Available,' in scl
    assert '#PID_Control_Enable := #Mode_Manual OR #Mode_Remote_Auto OR #Mode_Stage_Auto OR #Mode_Local_Auto;' in scl


def test_local_automatic_pid_does_not_require_remote_heartbeat():
    scl = source()

    assert 'SAC_Enable := #PID_Control_Enable,' in scl
    assert 'Remote_Comms_Required := #Mode_Remote_Auto,' in scl
    assert '(#Remote_Comms_Required AND (NOT #Remote_Comms_OK))' in scl
    assert '#System_Alarm_Light := NOT #Remote_Comms_OK;' in scl


def test_offline_adaptive_pid_uses_precision_deadbands():
    scl = source()

    assert 'EC_Deadband := 0.005,' in scl
    assert 'pH_Deadband := 0.005,' in scl
    assert '#Kp_EC_Eff := #Kp_EC *' in scl
    assert '#Ki_EC_Eff := #Ki_EC *' in scl
    assert '#Kd_EC_Eff := #Kd_EC *' in scl
    assert '#Adaptive_PID_Active_Out := (#Controller_Mode = 1) AND NOT #Fixed_PID_Test_Enable;' in scl
    assert 'Controller_Mode := "DB1".Controller_Mode,' in scl
    assert 'Fixed_PID_Test_Enable := "DB1".Fixed_PID_Test_Enable AND "DB1".Remote_Comms_OK,' in scl


def test_local_precision_bias_does_not_change_published_crop_target():
    scl = source()

    assert '#Control_EC_SP := #Active_EC_SP + #Local_EC_Bias;' in scl
    assert '#Control_pH_SP := #Active_pH_SP + #Local_pH_Bias;' in scl
    assert 'Local_Fallback_Mode := (#Mode_Manual OR #Mode_Stage_Auto OR #Mode_Local_Auto),' in scl
    assert 'Local_EC_Bias := 0.0,' in scl
    assert 'Local_pH_Bias := 0.0,' in scl


def test_manual_mode_uses_pid_targets_not_direct_flow_commands():
    scl = source()

    assert 'IF "DB1".Manual_PumpValve_Enable THEN' not in scl
    assert 'IF #Mode_Standby OR #Mode_Manual THEN' not in scl
    assert '"DB1".Stage_Auto_SP_Enable := TRUE;' in scl
