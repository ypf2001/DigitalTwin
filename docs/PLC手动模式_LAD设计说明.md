# PLC 手动模式 LAD 设计说明

更新日期：2026-07-07

适用工程：

```text
D:\dw_plc\xiaweiji\xiaweiji.ap21
D:\dw_plc\xiaweiji\src\xiaweiji.scl
```

## 1. 设计结论

当前采用混合实现：

- 梯形图 LAD：手动/自动模式、急停、通信正常判断、手动泵阀使能、报警灯、q_f/q_a 手动输出选择、自动/手动互锁。
- SCL：EC/pH 前馈、模糊 PID、N/P/K 分配、限幅、斜坡限制、模拟量换算。

原因是手动调试和试验台联锁需要在 TIA 在线监控中直观看到，适合 LAD；连续量控制算法包含大量 REAL 运算和限幅，继续保留 SCL 更稳定。

## 2. DB1 手动模式地址

这些变量已经追加在 `DB1` 末尾，未改变原有 `0..274` 地址：

| 变量 | 地址 | 类型 | 用途 |
| --- | ---: | --- | --- |
| `Manual_Mode` | `DBX278.0` | Bool | 手动模式命令 |
| `Auto_Mode` | `DBX278.1` | Bool | 预留自动模式命令 |
| `Emergency_Stop` | `DBX278.2` | Bool | 软件急停 |
| `Manual_Active` | `DBX278.3` | Bool | PLC 当前手动有效 |
| `Auto_Active` | `DBX278.4` | Bool | PLC 当前自动有效 |
| `Manual_q_f_Set` | `DBD280` | Real | 手动肥液流量设定，0..10 L/min |
| `Manual_q_a_Set` | `DBD284` | Real | 手动酸液流量设定，0..4 L/min |
| `Manual_q_n_Set` | `DBD288` | Real | 手动氮肥通道设定 |
| `Manual_q_p_Set` | `DBD292` | Real | 手动磷肥通道设定 |
| `Manual_q_k_Set` | `DBD296` | Real | 手动钾肥通道设定 |
| `Comm_Normal` | `DBX300.0` | Bool | LAD 通信正常判断 |
| `Manual_PumpValve_Enable` | `DBX300.1` | Bool | LAD 手动泵阀使能 |
| `Manual_q_f_Selected` | `DBD304` | Real | LAD 选择后的手动肥液流量 |
| `Manual_q_a_Selected` | `DBD308` | Real | LAD 选择后的手动酸液流量 |

## 3. 梯形图网络

### Network 1：急停最高优先级

```text
|----[ "DB1".Emergency_Stop ]----------------------------( "DB1".System_Alarm_Light )----|

|----[ "DB1".Emergency_Stop ]----------------------------(R "DB1".Manual_Active )--------|
|----[ "DB1".Emergency_Stop ]----------------------------(R "DB1".Auto_Active )----------|
```

急停触发后，所有执行量必须归零。实际归零动作当前在 `FC_CallFertigationControl` 的 SCL 分支中完成：

```text
q_f_cmd/q_a_cmd/q_n_cmd/q_p_cmd/q_k_cmd := 0
AQ_Valve_F/A/N/P/K_Raw := 0
```

### Network 2：手动模式有效

```text
|----[/ "DB1".Emergency_Stop ]----[ "DB1".Manual_Mode ]----------------( "DB1".Manual_Active )----|
```

含义：

```text
Manual_Active = Manual_Mode AND NOT Emergency_Stop
```

### Network 3：自动模式有效

```text
|----[/ "DB1".Emergency_Stop ]----[/ "DB1".Manual_Mode ]---------------( "DB1".Auto_Active )------|
```

当前自动模式不依赖 `Auto_Mode`，因为现有自动闭环入口仍由 `SAC_Enable`、阶段设定和通信状态共同决定。`Auto_Mode` 先作为后续本地自动/远程自动选择的预留位。

### Network 4：手动肥液和酸液输出选择

```text
|----[ "DB1".Manual_Active ]----[LIMIT 0.0, "DB1".Manual_q_f_Set, 10.0]----[RateLimiter F]----( "DB1".q_f_cmd )----|

|----[ "DB1".Manual_Active ]----[LIMIT 0.0, "DB1".Manual_q_a_Set,  4.0]----[RateLimiter A]----( "DB1".q_a_cmd )----|
```

TIA 中如果用 LAD 绘制，建议使用：

- `LIMIT` 或比较器 + `MOVE` 做上下限保护。
- 已有 `RateLimiter` FB 保持斜坡限制，避免泵阀突然跳变。
- 手动模式退出后，自动 SCL 分支重新接管 `q_f_cmd/q_a_cmd`。

### Network 5：手动 N/P/K 输出选择

```text
|----[ "DB1".Manual_Active ]----[LIMIT 0.0, "DB1".Manual_q_n_Set, "DB1".N_Max]----( "DB1".q_n_cmd )----|

|----[ "DB1".Manual_Active ]----[LIMIT 0.0, "DB1".Manual_q_p_Set, "DB1".P_Max]----( "DB1".q_p_cmd )----|

|----[ "DB1".Manual_Active ]----[LIMIT 0.0, "DB1".Manual_q_k_Set, "DB1".K_Max]----( "DB1".q_k_cmd )----|
```

N/P/K 三路当前不加斜坡，原因是它们是独立计量通道设定值。若实际泵响应过快，后续可以复用 `RateLimiter` 扩展三路斜坡。

### Network 6：模拟量输出换算

```text
|----[ "DB1".Manual_Active ]----[q_f_cmd / 10.0 * 27648.0]----[REAL_TO_INT]----( "DB1".AQ_Valve_F_Raw )----|

|----[ "DB1".Manual_Active ]----[q_a_cmd /  4.0 * 27648.0]----[REAL_TO_INT]----( "DB1".AQ_Valve_A_Raw )----|

|----[ "DB1".Manual_Active ]----[q_n_cmd / N_Max * 27648.0]---[REAL_TO_INT]----( "DB1".AQ_Valve_N_Raw )----|
|----[ "DB1".Manual_Active ]----[q_p_cmd / P_Max * 27648.0]---[REAL_TO_INT]----( "DB1".AQ_Valve_P_Raw )----|
|----[ "DB1".Manual_Active ]----[q_k_cmd / K_Max * 27648.0]---[REAL_TO_INT]----( "DB1".AQ_Valve_K_Raw )----|
```

注意：当 `N_Max/P_Max/K_Max <= 0` 时，对应模拟量必须直接写 0，避免除零。

## 4. 当前代码对应关系

当前可运行实现位于 `FC_CallFertigationControl`：

```text
D:\dw_plc\xiaweiji\src\xiaweiji.scl
```

对应逻辑：

```text
急停分支
    Emergency_Stop = TRUE -> 所有执行量归零，报警灯置位，RETURN

手动分支
    Manual_Mode = TRUE -> Manual_Active = TRUE
    限幅 Manual_q_*_Set
    q_f/q_a 经过 RateLimiter
    q_n/q_p/q_k 直接限幅输出
    换算 AQ_Valve_*_Raw
    RETURN

自动分支
    Manual_Active = FALSE
    Auto_Active = TRUE
    调用 FB_FertigationControl
```

## 5. 试验台上电顺序

1. 确认真实急停按钮、电源断路、泵阀电源隔离先可用。
2. 在 PLC 中清零 `Emergency_Stop`，并确认 `System_Alarm_Light = FALSE`。
3. 先写入很小的手动流量，例如 `q_f=0.2`、`q_a=0.0`、`q_n/q_p/q_k=0.0`。
4. 置位 `Manual_Mode`，观察 `Manual_Active = TRUE`、`Auto_Active = FALSE`。
5. 观察 `AQ_Valve_*_Raw` 是否按比例变化。
6. 测试 `Emergency_Stop = TRUE` 后所有 `q_*_cmd` 和 `AQ_Valve_*_Raw` 是否立即归零。
7. 清除急停，退出 `Manual_Mode`，再进入自动/PLCSIM 验证。

## 6. 后续可改成真实 LAD 块的边界

后续若要在 TIA 中完全形成 LAD 块，建议只迁移以下内容：

- `Manual_Active/Auto_Active` 互锁。
- 急停归零。
- 手动设定限幅。
- 手动模拟量换算。

不要把 `FB_FertigationControl` 的 EC/pH 控制算法全部改成 LAD。那部分在论文和工程上都更适合作为 SCL 算法块说明。

## 7. 本次验证记录

2026-07-07 已通过 Python Openness 将当前 SCL 导入 TIA 工程并编译：

```text
Project: xiaweiji
PLC software: PLC_1
Compile state: Warning
Errors: 0
Warnings: 6
Project saved: yes
```

结论：手动模式代码没有编译错误，可以进入下载/PLCSIM 验证阶段。6 个 warning 需要在 TIA 的编译信息窗口中逐条查看，但当前不是阻断项。

同日执行 `scripts/plc_manual_mode_smoke.py` 默认 dry run 时，未写入 DB1；连接 `127.0.0.1:102` 被对端关闭，说明当前 Snap7/PLCSIM 运行链路还没有连通。后续在 PLCSIM Advanced 或真实 PLC 处于 RUN 且工程已下载后，再执行：

```powershell
python scripts\plc_manual_mode_smoke.py --apply --q-f 0.2 --q-a 0.0 --q-n 0.0 --q-p 0.0 --q-k 0.0
```

## 8. LAD 实施记录

2026-07-07 已将离散控制和手动输出选择正式拆成 LAD 块：

```text
FC_ModeInterlock_LAD
ProgrammingLanguage: LAD
Block number: FC 2
```

LAD 网络：

```text
Network 1: Comm_Normal = Remote_Comms_OK AND NOT Emergency_Stop
Network 2: Manual_Active = Manual_Mode AND NOT Emergency_Stop
Network 3: Auto_Active = Auto_Mode AND NOT Manual_Mode AND NOT Emergency_Stop
Network 4: Manual_PumpValve_Enable = Manual_Active
Network 5: System_Alarm_Light = NOT Comm_Normal
Network 6: Manual_PumpValve_Enable -> MOVE Manual_q_f_Set to Manual_q_f_Selected
Network 7: Manual_PumpValve_Enable -> MOVE Manual_q_a_Set to Manual_q_a_Selected
```

`FC_CallFertigationControl` 现在先调用该 LAD 块：

```scl
"FC_ModeInterlock_LAD"();
```

本地手动不依赖 `Remote_Comms_OK` 或 `Comm_Normal`。通信异常仍会置位报警灯，并禁止依赖上位机的远程自动，但不会阻止 HMI/控制柜手动点动。

然后 SCL 只根据 `DB1.Manual_PumpValve_Enable` 进入手动连续量控制分支。也就是说，模式互锁、通信判断、报警灯和 q_f/q_a 手动选择已经是梯形图；EC/pH 前馈、模糊 PID、N/P/K 分配和复杂数学仍保留在 SCL。

验证结果：

```text
FC_ModeInterlock_LAD: LAD, IsConsistent=True
FC_CallFertigationControl: SCL, IsConsistent=True
Whole PLC compile: 0 errors, 0 warnings
```

## 9. 本地手动解除通信依赖

2026-07-10 将 Network 4 从：

```text
Manual_PumpValve_Enable = Manual_Active AND Comm_Normal
```

改为：

```text
Manual_PumpValve_Enable = Manual_Active
```

因此上位机通信断开时，只要 `Manual_Mode = TRUE` 且未急停，本地 HMI/控制柜仍可进行手动点动。`Comm_Normal` 继续用于通信报警，远程自动仍由通信看门狗保护。

已通过 Openness 导入 `FC_ModeInterlock_LAD`、编译并保存工程：

```text
Compile state: Success
Errors: 0
Warnings: 0
Project saved: yes
```

随后从 TIA 工程回读导出 Network 4，确认仅包含：

```text
Manual_Active -> Manual_PumpValve_Enable
```

回读文件：`docs/tia_export_FC_ModeInterlock_LAD_local_manual.xml`。
