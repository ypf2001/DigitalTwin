# KTP900 HMI 界面设计

更新日期：2026-07-24

适用对象：

```text
HMI_1 [KTP900 Basic]
PLC 工程：D:\dw_plc\xiaweiji\xiaweiji.ap21
PLC 通信 DB：DB1
```

## 1. 设计目标

当前 HMI 不做“花哨展示”，而是服务于三件事：

- 现场快速判断系统是否正常运行。
- 试验台联调时能安全地切换自动/手动并测试泵阀。
- 论文实验阶段能稳定查看关键参数、报警和调参结果。

界面风格建议：

- 横屏 800x480，深灰背景，状态色高对比。
- 顶部固定状态栏，底部固定导航栏。
- 每个页面只保留最核心的操作，避免在同一页堆太多输入框。

## 2. 全局框架

### 顶部状态栏

所有页面共用，建议高度 `48 px`。

左侧：

- 系统名称：`马铃薯水肥控制系统`
- 日期时间

右侧：

- 通讯状态灯：绑定 `Remote_Comms_OK`
- 运行模式：优先显示 `Manual_Active` / `Auto_Active`
- 报警灯图标：绑定 `System_Alarm_Light`

状态色建议：

- 正常：绿色
- 手动：橙色
- 报警/急停：红色
- 离线/通讯异常：灰红色闪烁

### 底部导航栏

所有页面共用，建议高度 `54 px`。

按钮顺序：

1. `主监控`
2. `手动调试`
3. `参数设置`
4. `报警诊断`
最终投运画面固定为 `主监控`、`手动调试`、`报警诊断`、`PID 参数` 四页；趋势保留为可选诊断页。

### 统一交互规则

- `Emergency_Stop` 和 `Physical_EStop_OK` 始终只读；HMI 停机命令只写 `Soft_Stop_Request`。
- `Actuator_Enable_Request`、PID、量程和标定参数仅工程师权限可写。
- 只有 `Manual_Mode=TRUE` 且 `Comm_Normal=TRUE` 时，手动泵阀输入区域高亮。
- 参数设置页默认只允许工程师修改，建议加密码等级。
- 报警页始终允许访问，不做权限限制。

## 3. 画面 1：主监控画面

画面名建议：

```text
Screen_01_MainOverview
```

用途：

- 运行时总览。
- 适合常驻显示。

布局建议：

- 左半区：EC/pH 状态
- 右半区：模式、通讯、报警
- 下半区：执行量和阀门输出

### 区块 A：EC/pH 总览

建议放四个大数字框：

- `EC_Set_SP`
- `EC_Actual`
- `pH_Set_SP`
- `pH_Actual`

补充显示：

- `Active_EC_SP`
- `Active_pH_SP`
- `Growth_Stage`

显示规则：

- 实际值大字显示
- 设定值小字显示
- 若 `Setpoint_Protection_Active=TRUE`，在设定值旁显示 `保护中`

### 区块 B：系统状态

建议用状态灯或图标：

- `Remote_Comms_OK`
- `Comm_Normal`
- `System_Alarm_Light`
- `Emergency_Stop`
- `Physical_EStop_OK`
- `Field_IO_Ready`
- `Actuator_Enable_Permitted`
- `Manual_Active`
- `Auto_Active`

状态文字建议：

- `通讯正常 / 通讯中断`
- `自动运行 / 手动调试 / 急停锁定`

### 区块 C：执行量监控

建议显示条形图 + 数字：

- `q_f_cmd`
- `q_a_cmd`
- `Valve_F_Actual`
- `Valve_A_Actual`
- `AQ_Valve_F_Raw`
- `AQ_Valve_A_Raw`
- `Qw_Actual` / `Pressure_Actual` / `Water_Pump_Run_CMD`

补充显示：

- `q_n_cmd`
- `q_p_cmd`
- `q_k_cmd`

### 主监控页建议补充

- 页面右上角增加一个 `跳转手动调试` 快捷按钮。
- 页面底部增加 `最近报警摘要` 一行文本，来自报警页主要状态。

## 4. 画面 2：手动与调试画面

画面名建议：

```text
Screen_02_ManualControl
```

用途：

- 现场测试泵阀和手动输出。
- 联调 PLC 手动模式。

布局建议：

- 顶部：模式切换与急停状态
- 中部：手动设定输入
- 右侧：手动选择结果与使能状态
- 底部：操作提示

### 区块 A：模式控制

建议放置：

- `手动模式按钮` -> 绑定 `Manual_Mode`
- `自动模式按钮` -> 绑定 `Auto_Mode`
- `实体急停状态指示` -> 绑定只读 `Physical_EStop_OK`
- `软停按钮` -> 绑定 `Soft_Stop_Request`

按钮规则：

- `Manual_Mode` 和 `Auto_Mode` 使用两态按钮或切换按钮，不用普通瞬时按钮。
- HMI 不得写 `Emergency_Stop`；实体急停硬接接触器或驱动 STO，PLC 只读辅助反馈。
- `Actuator_Enable_Request` 仅工程师登录后可写，且不能绕过钥匙、急停和 I/O 许可。

### 区块 B：手动输入区

输入域：

- `Manual_q_f_Set`
- `Manual_q_a_Set`
- `Manual_q_n_Set`
- `Manual_q_p_Set`
- `Manual_q_k_Set`

推荐限制：

- `q_f`: `0.0 ~ 10.0`
- `q_a`: `0.0 ~ 4.0`
- `q_n/q_p/q_k`: `0.0 ~ 对应 Max`

建议控件：

- `q_f`、`q_a` 用数值输入 + 小步进按钮
- `q_n/q_p/q_k` 用紧凑输入框放在下方一行

### 区块 C：手动执行链路反馈

显示只读状态：

- `Manual_Active`
- `Manual_PumpValve_Enable`
- `Manual_q_f_Selected`
- `Manual_q_a_Selected`
- `q_f_cmd`
- `q_a_cmd`

这个区块很重要，因为它能直接验证：

- 模式是否真的切到手动
- 通讯正常判断是否通过
- LAD 是否已经把手动设定送入执行链路

### 区块 D：调试提示

固定提示文字建议：

```text
建议先清除急停，再从小流量开始测试。
推荐起始值：q_f=0.2, q_a=0.0。
```

## 5. 画面 3：参数设置画面

画面名建议：

```text
Screen_03_PID_Settings
```

用途：

- 工程师在线调参。
- 管理 PID 和 N/P/K 配方比例。

布局建议：

- 左半区：EC / pH PID
- 右半区：N / P / K 通道配置
- 底部：安全开关与阶段设定

### 区块 A：EC PID

输入域：

- `Kp_EC_Set`
- `Ki_EC_Set`
- `Kd_EC_Set`

附加显示：

- `EC_Trim_Band`
- `Active_EC_SP`

### 区块 B：pH PID

输入域：

- `Kp_pH_Set`
- `Ki_pH_Set`
- `Kd_pH_Set`

附加显示：

- `pH_Trim_Band`
- `Active_pH_SP`

### 区块 C：N/P/K 配方参数

每个通道建议一行：

- `N_Enable` / `N_Ratio` / `N_Max`
- `P_Enable` / `P_Ratio` / `P_Max`
- `K_Enable` / `K_Ratio` / `K_Max`

建议说明：

- `Enable` 当前在 PLC 中是 `REAL`，HMI 可做成 `0.0/1.0` 切换按钮。
- `Ratio` 建议保留 3 位小数。

### 区块 D：运行策略参数

建议增加：

- `Growth_Stage`
- `Stage_Auto_SP_Enable`
- `Stage_EC_SP`
- `Stage_pH_SP`

用途：

- 便于现场切换当前阶段。
- 验证论文阶段控制逻辑时很方便。

## 6. 画面 4：报警与诊断

画面名建议：

```text
Screen_04_AlarmsDiagnostics
```

用途：

- 快速判断故障来源。
- 诊断通信链路、急停、模式状态。

布局建议：

- 左侧：报警摘要
- 右侧：诊断变量
- 下方：执行链路快照

### 区块 A：报警摘要

显示：

- `System_Alarm_Light`
- `Emergency_Stop`
- `Remote_Comms_OK`
- `Comm_Normal`
- `Field_IO_Ready`
- `Actuator_Enable_Permitted`
- `Sensor_Fault_Any`
- `Drive_Fault_Any`

报警文字建议：

- `急停触发`
- `上位机通信异常`
- `系统处于报警状态`
- `自动模式不可用`

### 区块 B：通信诊断

显示：

- `Remote_Heartbeat`
- `Remote_Comms_OK`
- `Watchdog_Timer`
- `Watchdog_Count`
- `Remote_Comms_Was_OK`

这部分是诊断 HIL/PLCSIM 最有用的区域。

### 区块 C：模式与联锁诊断

显示：

- `Manual_Mode`
- `Auto_Mode`
- `Manual_Active`
- `Auto_Active`
- `Manual_PumpValve_Enable`

目的：

- 用于判断是“按钮没切过去”，还是“LAD 联锁没放行”。

### 区块 D：执行链路快照

显示：

- `Manual_q_f_Set`
- `Manual_q_f_Selected`
- `Manual_q_a_Set`
- `Manual_q_a_Selected`
- `q_f_cmd`
- `q_a_cmd`

## 7. 补充页面建议

### 画面 5：趋势与实验记录

画面名建议：

```text
Screen_05_Trends
```

建议显示趋势：

- `EC_Actual`
- `pH_Actual`
- `q_f_cmd`
- `q_a_cmd`

如果 KTP900 Basic 的趋势资源有限，至少保留：

- `EC_Actual`
- `pH_Actual`

### 公共弹窗

建议增加两个弹窗：

1. `模式切换确认`
2. `急停状态提示`

## 8. 画面实施顺序

建议你在博途中按这个顺序做：

1. 先建 HMI 标签。
2. 先做 `主监控`，确认基本读数都能显示。
3. 再做 `手动调试`，优先验证 `Manual_Mode`、`Manual_PumpValve_Enable`、`Manual_q_f_Selected/q_a_Selected`。
4. 再做 `报警诊断`，方便联调时查问题。
5. 最后做 `参数设置` 和 `趋势`。

## 9. 当前最关键的 HMI 变量

如果你想先做最小可用版本，优先绑定这些：

- `EC_Set_SP`
- `EC_Actual`
- `pH_Set_SP`
- `pH_Actual`
- `Remote_Comms_OK`
- `System_Alarm_Light`
- `Manual_Mode`
- `Auto_Mode`
- `Emergency_Stop`
- `Manual_Active`
- `Auto_Active`
- `Manual_PumpValve_Enable`
- `Manual_q_f_Set`
- `Manual_q_a_Set`
- `Manual_q_f_Selected`
- `Manual_q_a_Selected`
- `q_f_cmd`
- `q_a_cmd`
- `Watchdog_Timer`
- `Watchdog_Count`
