# PLC Deployment Readiness

本文档定义当前系统从纯仿真过渡到真实 PLC/水肥机时的稳定结构。目标是：后续现场部署只改参数和接线映射，尽量不改主控制逻辑。

## 1. 当前部署边界

当前已经固定的控制结构：

```text
上位机 / 数字孪生 / SAC
  -> 写 EC_Set_SP、pH_Set_SP、EC_Actual、pH_Actual、SAC_Enable、Remote_Heartbeat

PLC FB_FertigationControl
  -> 目标保护
  -> 反馈滤波
  -> EC 前馈 + 模糊自适应 PID
  -> pH 连续前馈 + 模糊自适应 PID + 提前停酸
  -> 限幅和斜坡限速
  -> 输出 q_f_cmd、q_a_cmd

过程对象
  -> 混合罐 / 管道 / 真实传感器
  -> 产生新的 EC_Actual、pH_Actual
```

当前执行通道：

```text
q_f_cmd: 1 路复合肥母液
q_a_cmd: 1 路酸液
q_w: 清水流量，当前作为过程参数，不由 PLC 输出
```

## 2. DB1 通讯契约

真实部署时，DB1 地址必须保持和 `config/simulation.yaml` 的 `plc.addresses` 一致。

上位机写入：

```text
EC_Set_SP
pH_Set_SP
EC_Actual
pH_Actual
SAC_Enable
Remote_Heartbeat
Growth_Stage
Kp_EC_Set / Ki_EC_Set / Kd_EC_Set
Kp_pH_Set / Ki_pH_Set / Kd_pH_Set
```

上位机读取：

```text
Remote_Comms_OK
Watchdog_Timer
Active_EC_SP
Active_pH_SP
Setpoint_Protection_Active
q_f_cmd
q_a_cmd
Valve_F_Actual
Valve_A_Actual
System_Alarm_Light
```

注意：

```text
Stage_Auto_SP_Enable = TRUE 且 SAC_Enable = FALSE 时，PLC 使用本地阶段目标。
SAC_Enable = TRUE 时，上位机目标优先生效。
```

## 3. 现场部署需要标定的参数

这些参数不能只相信仿真值，现场必须重新测：

```text
清水流量 q_w
原水 EC / pH
肥液母液 EC
酸液 pH
酸液对 EC 的贡献系数
肥液泵流量曲线
酸液泵流量曲线
管道纯延迟 tau
管道一阶惯性 T
EC/pH 传感器响应延迟和滤波需求
```

集中记录位置：

```text
config/deployment.yaml
```

## 4. 推荐上线顺序

```text
1. 纯仿真出口闭环
2. PLCSIM 出口闭环
3. 真实 PLC + 模拟反馈
4. 真实 PLC + 真实传感器 + 清水
5. 单路复合肥 + 酸液出口闭环
6. 管道延迟/预充策略
7. 固定阶段田间模型
8. 全生命周期
9. 未来扩展 A/B/C 多路肥液
```

## 5. 多路肥液扩展原则

当前 `q_f_cmd` 是总复合肥流量。未来扩展多路肥液时，不废弃当前 EC 控制器，而是改名理解为：

```text
q_f_total_cmd
```

再按配方比例拆分：

```text
q_f_A_cmd = q_f_total_cmd * W_A
q_f_B_cmd = q_f_total_cmd * W_B
q_f_C_cmd = q_f_total_cmd * W_C
```

pH 酸液通道仍然独立控制。

## 6. 每次部署前预检

运行：

```powershell
cd "D:\Digital Twin"
.\.venv\Scripts\python.exe .\plc\tools\deployment_preflight.py
```

连接 PLC/PLCSIM 一起检查：

```powershell
.\.venv\Scripts\python.exe .\plc\tools\deployment_preflight.py --connect
```
