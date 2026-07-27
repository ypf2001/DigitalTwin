# 马铃薯水肥一体化数字孪生与 SAC-PID 控制系统

本项目包含马铃薯滴灌水肥一体化的数字孪生、SAC 上层决策、PLC/PID 执行、PLCSIM 在环测试，以及后续现场辨识流程。

当前采用分层架构：

```text
数字孪生状态 / 现场传感器
        -> SAC 上层决策
        -> EC_Set_SP, pH_Set_SP
        -> PLC/PID 执行层
        -> q_f_cmd, q_a_cmd, q_n_cmd, q_p_cmd, q_k_cmd
        -> 肥泵、酸泵、N/P/K 泵和主水泵
        -> EC/pH 反馈
```

SAC 只输出 EC/pH 目标，不直接控制泵。PLC 负责 PID、前馈、限幅、斜率限制、通信联锁、急停和执行器安全。

## 当前状态

当前阶段是 **PLCSIM 局部辨识和 A/B 验证阶段**，尚未进入真实泵和真实传感器测试。

已完成：

- MID 阶段低、中、高三个工作点的 PLCSIM 局部 G 矩阵辨识。
- Python 多工作点 G 表和最近点选择逻辑。
- PLC 手动模式、远程自动模式和待机模式验证。
- PLC SCL 经 Openness 导入、编译和下载。
- 编译：`0 errors, 21 warnings`。
- PLCSIM 下载：`0 errors, 0 warnings`。
- MID 工作点四档权重 A/B：`0, 0.1, 0.25, 0.5`。
- A/B 判据自动化和结果报告。

当前未通过：

- pH 阶跃方向的交叉耦合仅降低约 3.2%~5.2%，未达到 10% 验收门槛。
- 部分权重增加 EC 误差或泵限幅。
- `Decoupler_Enable` 不能打开。
- 真实设备测试不能开始。

当前 PLC 安全状态：

```text
Emergency_Stop = TRUE
Manual_Mode = FALSE
Auto_Mode = FALSE
q_f_cmd = 0
q_a_cmd = 0
G_EC_F = G_EC_A = G_pH_F = G_pH_A = 0
Decoupler_Weight = 0
Decoupler_Enable = FALSE
Decoupler_Valid = FALSE
```

待机时 `System_Alarm_Light` 可能因为没有上位机心跳而为 TRUE；同时检查 `Actuator_Any_Alarm`、`Actuator_Any_Trip` 和 `Actuator_Execution_Enable`。

## 参数分工

### PLC DB1

PLC 保存实时执行参数：

- EC/pH PID：`Kp_*_Set`、`Ki_*_Set`、`Kd_*_Set`。
- 当前活动 G：`G_EC_F`、`G_EC_A`、`G_pH_F`、`G_pH_A`。
- 当前权重：`Decoupler_Weight`。
- 流量限幅：`q_f_min`、`q_f_max`、`q_a_min`、`q_a_max`。
- 延迟：`Mixing_Delay_s`。
- N/P/K 比例、启用状态和泵上限。
- 模式、通信、急停、报警和执行器诊断位。

DB1 既有字段偏移不能移动；新字段只能追加到末尾，并同步维护 `config/simulation.yaml`。

### Python 上位机

Python 保存完整 G 表、工作点选择、噪声模型、混合罐、管道、土壤、作物模型、实验数据和 A/B 报告。

```text
config/gain_schedule.yaml
```

该文件当前有 MID 的 `low/medium/high` 三个点，但总开关保持：

```yaml
gain_schedule:
  enabled: false
```

### SAC

SAC 动作空间为：

```text
[EC_Set_SP, pH_Set_SP]
```

SAC 不直接输出 `q_f`、`q_a` 或 N/P/K 泵指令。

## 主要程序

| 文件 | 作用 |
|---|---|
| `digital_twin_env.py` | 非线性数字孪生核心 |
| `digital_twin_gym_env.py` | Gymnasium 封装 |
| `mixing_tank.py` | 肥液、酸液和清水混合 |
| `pipe_dynamics.py` | 管道延迟和一阶惯性 |
| `soil_profile_v2.py` | 分层土壤水盐状态 |
| `soil_transport.py` | 土壤水盐迁移 |
| `crop_model.py` | 生育期、ETc、目标 EC 和根深 |
| `water_pump.py` | 主水泵流量、压力和批次 |
| `train_sac.py` | SAC 训练 |
| `eval_sac.py` | SAC 评估 |
| `plc_client.py` | S7/PLCSIM 通信主接口 |
| `plc_gym_env.py` | PLC/PLCSIM HIL 环境 |
| `plc_control/gain_schedule.py` | G 表加载、选择和辨识 |
| `plc_control/ab_validation.py` | A/B 判定 |
| `experiments/run_plc_gain_identification.py` | PLCSIM 局部 G 辨识 |
| `experiments/run_plc_decoupler_ab.py` | 四档权重 A/B |
| `experiments/evaluate_plc_decoupler_ab.py` | 离线评估 A/B 报告 |
| `experiments/run_plc_setpoint_step.py` | PLC 出口阶跃测试 |
| `scripts/plc_manual_mode_smoke.py` | 手动模式烟测 |
| `scripts/plc_mode_handoff_validation.py` | 模式切换验证 |
| `scripts/diagnose_plc_issue.py` | PLC 通信和 DB1 诊断 |

当前主通信链：

```text
plc_client.py + plc_gym_env.py
```

## PLC 程序

Canonical SCL：

```text
plc/xiaweiji/src/xiaweiji.scl
```

主要模块：

- `DB1`：通信、目标、PID、G 矩阵、限幅和诊断。
- `FB_FertigationControl`：前馈、PID、局部解耦、限幅和防积分饱和。
- `FC_CallFertigationControl`：模式解析、目标保护、G 有效性检查和 FB 调用。
- `FC_ModeSelector_LAD`：手动、远程自动、阶段自动、本地自动和待机。
- `FC_ModeInterlock_LAD`：急停、通信、泵阀和报警联锁。
- `FB_DosingPump`：泵流量闭环和断流报警。
- `DB_Actuator`：泵标定和反馈参数。

解耦只有在以下条件同时满足时才会执行：

```text
Decoupler_Enable = TRUE
Decoupler_Valid = TRUE
abs(det(G)) >= Decoupler_Determinant_Min
G_EC_F > 0
G_pH_A < 0
```

G 有效性检查位于急停和待机提前返回之前，保证待机时 DB1 诊断不会保留旧值。

## 安装和验证

```powershell
cd "D:\Digital Twin"
pip install -r requirements.txt
python -m py_compile plc_client.py experiments\run_plc_gain_identification.py experiments\run_plc_decoupler_ab.py
pytest -q tests\test_gain_schedule.py tests\test_control_parameters_contract.py tests\test_plc_mode_handoff.py
```

当前上述相关测试为 `16 passed`。全量测试中另有一个无关的土壤模型浮点精确比较问题：`tests/test_soil_profile_v2.py`。

## PLCSIM 局部 G 辨识

辨识前确认：

```text
Manual_Mode = FALSE
Auto_Mode = FALSE
Emergency_Stop = TRUE
Decoupler_Enable = FALSE
```

执行：

```powershell
python experiments\run_plc_gain_identification.py --apply --point low --plc-wait-s 0.1
python experiments\run_plc_gain_identification.py --apply --point medium --plc-wait-s 0.1
python experiments\run_plc_gain_identification.py --apply --point high --plc-wait-s 0.1
```

每个点执行稳定基线、肥泵正负阶跃、酸泵正负阶跃和恢复段。结果保存到 `results/plc_gain_identification/<run_id>/`。必须检查 `valid`、G 符号、行列式、条件数、延迟、时间常数和正负阶跃一致性。

## PLCSIM A/B 验证

当前 A/B 脚本先预热，再进行 EC 和 pH 单变量阶跃：

```powershell
python experiments\run_plc_decoupler_ab.py `
  --apply --point medium --duration-s 600 --warmup-s 600 `
  --sim-step-s 10 --plc-wait-s 0.1
```

默认权重为 `0, 0.1, 0.25, 0.5`。pH 测试使用 `5.9 -> 6.05`，避免触发 PLC 的 `5.8` 下限。

判据文件：`config/decoupler_ab.yaml`。

判定要求：

- EC 和 pH 两种阶跃方向都改善。
- 交叉耦合至少降低 10%。
- EC/pH MAE 增加不超过 0.01。
- 泵限幅次数不增加。
- 报警、通信故障和目标保护不增加。

当前结果位于 `results/plc_decoupler_ab/20260718_163434/`，其中 `Weight=0.1/0.25/0.5` 均未通过。
交叉耦合峰值采用阶跃前最后 120 s 实际稳态均值作为基线，不再把设定值跟踪偏差计入耦合量。
重分析结果保存在 `summary_reanalyzed.json` 和 `ab_verdict_reanalyzed.json`：EC 阶跃方向降低约
17.0%~21.8%，pH 阶跃方向降低约 3.2%~5.2%；同时 EC 阶跃的 EC MAE 增加约
0.039~0.043，因此当前仍不允许启用解耦。

离线重新评估：

```powershell
python experiments\evaluate_plc_decoupler_ab.py `
  results\plc_decoupler_ab\20260718_163434\summary.json
```

## TIA Portal 编译和下载

工程导入、编译、保存和下载统一通过 `tia_portal` MCP 完成，不再由 Python 直接调用 Openness。使用 `$tia-portal-openness`，按以下顺序执行：

```text
Bootstrap -> Connect -> AttachToOpenProject/OpenProject -> GetProjectTree
-> 导入或修改 -> CompileAndDiagnosePlc -> SaveProject
```

下载前确认 `config/deployment.yaml` 使用正确的部署配置，并依次调用 `CheckDownloadReadiness` 和 `DownloadToPlc`。Snap7 的 `plc_client.py` 仍只负责 PLC/PLCSIM 运行时数据通信。

## 手动模式烟测

```powershell
python scripts\plc_manual_mode_smoke.py --apply --q-f 0.2 --q-a 0
```

预期：`Manual_Active=True`、`q_f_cmd=0.2`、`q_a_cmd=0`。结束后执行：

```powershell
python -c "from plc_client import PLCClient; p=PLCClient(); p.connect(); p.write_standby(); p.write_emergency_stop(True); p.disconnect()"
```

## 真实设备测试门槛

真实设备不能直接替代 PLCSIM，必须按以下顺序：

```text
泵和流量计标定
-> 清水/回流系统验收
-> 真实肥泵单变量阶跃
-> 真实酸泵单变量阶跃
-> 真实 G 矩阵辨识
-> Weight=0 基线
-> Weight=0.1 小权重验证
-> 通过后才扩大范围
```

真实测试时，EC/pH 必须来自真实传感器；Python 只记录，不伪造 `EC_Actual` 和 `pH_Actual`。SAC 和解耦首轮都必须关闭，并使用回流或排液桶，不应直接进入作物根区。

## 故障排查

PLC 连接但输出为 0 时检查：

```text
Emergency_Stop
Manual_Mode / Auto_Mode
Manual_Active / Auto_Active
Remote_Comms_OK
Water_Flow_OK
Actuator_Execution_Enable
Actuator_Any_Alarm
Actuator_Any_Trip
```

`System_Alarm_Light=True` 可能只是上位机心跳未写入；必须区分通信报警和执行器报警。

如果解耦无法启用，确认 G 回读一致、`Decoupler_Valid=True`、行列式足够大，并且 A/B 报告明确通过。不要绕过 `PLCClient.set_decoupler_enabled()` 直接写 DB 位。

## 当前下一步

当前应继续分析 pH 通道，而不是进入真实设备：

1. 核对 `G_pH_F`、`G_pH_A` 的实际符号和单位。
2. 用 pH 泵单变量开环阶跃复核 pH 行增益。
3. 检查 PLC pH PID 误差方向和解耦公式方向。
4. 修正后重新运行同一套 A/B。
5. 只有某个权重在两个方向都通过判据，才允许准备真实设备测试。

在此之前保持：

```text
SAC 不直接控制泵
Decoupler_Enable = FALSE
真实设备测试 = 不执行
```
