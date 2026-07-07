# PLC 当前完成情况与后续研究流程

检查日期：2026-07-06

PLC 工程路径：`D:\dw_plc\xiaweiji\xiaweiji.ap21`

Python Openness 快照：`docs/plc_openness_snapshot_20260706.json`

## 1. Openness 读取结论

已通过 Python TIA Openness 接口附加到当前已打开的 TIA Portal 工程：

```text
Project: xiaweiji
PLC software: PLC_1
Compile state: Success
Errors: 0
Warnings: 0
```

说明：当前 PLC 工程不是只停留在源码层，TIA 工程内已经存在对应程序块，并且 `PLC_1` 编译通过。

## 2. 当前 PLC 工程块清单

| 块名                      |        类型 | 编号 | 语言 | 完成状态 |
| ------------------------- | ----------: | ---: | ---- | -------- |
| Main                      |          OB |    1 | LAD  | 已存在   |
| FB_CommsWatchdog_LAD      |          FB |    3 | LAD  | 已存在   |
| RateLimiter               |          FB |    1 | SCL  | 已实现   |
| inst_RL_A                 | Instance DB |    3 | DB   | 已生成   |
| inst_RL_F                 | Instance DB |    2 | DB   | 已生成   |
| DB1                       |   Global DB |    1 | DB   | 已实现   |
| FB_FertigationControl     |          FB |    2 | SCL  | 已实现   |
| inst_FertigationControl   | Instance DB |    4 | DB   | 已生成   |
| FC_CallFertigationControl |          FC |    1 | SCL  | 已实现   |

TIA 外部源中读取到：

```text
12.scl
xiaweiji_20260609_162145
xiaweiji
```

当前主源码：

```text
D:\dw_plc\xiaweiji\src\xiaweiji.scl
```

当前项目镜像：

```text
D:\Digital Twin\plc\xiaweiji\src\xiaweiji.scl
```

两份 SCL 的 SHA256 一致，说明 PLC 主仓和数字孪生项目镜像当前同步。

## 3. PLC 已完成的功能

### 3.1 上位机通信 DB1

`DB1` 已作为上位机 Python 与 PLC 的固定通信契约。

上位机写入：

- `EC_Set_SP`
- `pH_Set_SP`
- `EC_Actual`
- `pH_Actual`
- `SAC_Enable`
- `Remote_Heartbeat`
- `Growth_Stage`
- PID 参数和 N/P/K 通道参数

PLC 回读：

- `Remote_Comms_OK`
- `Watchdog_Timer`
- `Active_EC_SP`
- `Active_pH_SP`
- `Setpoint_Protection_Active`
- `q_f_cmd`
- `q_a_cmd`
- `q_n_cmd`
- `q_p_cmd`
- `q_k_cmd`
- `AQ_Valve_*_Raw`
- `System_Alarm_Light`

对应 Python 地址映射位于：

```text
config/simulation.yaml
plc_client.py
```

### 3.2 PLC 分层执行控制

当前 PLC 执行层已经实现：

- SAC/上位机只输出 `EC_set` 和 `pH_set`
- PLC 根据反馈计算肥液和酸液执行量
- `q_f_cmd` 表示总肥液流量
- `q_a_cmd` 表示酸液流量
- `q_n_cmd/q_p_cmd/q_k_cmd` 表示 N/P/K 三路计量泵流量

这与论文中的“上位机智能决策 + PLC 底层执行”分层控制路线一致。

### 3.3 安全保护与工程约束

已实现的工程安全逻辑：

- 心跳看门狗：`Remote_Heartbeat` 不变化时进入通信异常状态
- 通信异常归零：`SAC_Enable = false` 或通信超时时，执行量归零
- 生长阶段目标保护：不同阶段限制 EC/pH 目标范围
- 目标越界保护：越界时使用阶段安全目标
- 反馈滤波：对 EC/pH 反馈做低通滤波和输入跳变限制
- 泵阀斜坡限速：通过 `RateLimiter` 限制执行量变化速度
- 模拟量换算：将流量输出换算到 `0~27648` 模拟量原始值

### 3.4 控制算法状态

当前 PLC 控制器实际完成的是：

```text
前馈计算 + 模糊自适应 PID 修正 + 限幅 + 限速 + 安全保护
```

尚不是完整的：

```text
ESO-AFOPID
```

因此论文当前主线应先表述为：

```text
数字孪生驱动的 SAC-PLC 分层控制方法
PLC 执行层采用前馈与模糊自适应 PID 复合控制
```

ESO-AFOPID 可以作为后续增强模块或论文展望，不建议现在作为主线强行承诺。

## 4. 与上位机当前项目的衔接状态

上位机侧已经具备以下支撑：

- `plc_client.py`：Snap7 读写 PLC DB1
- `plc_gym_env.py`：PLC/PLCSIM 在环 Gym 环境
- `run_hil.py`：HIL 推理入口
- `sac_model_registry.py`：四阶段 SAC 模型统一映射
- `config/simulation.yaml`：PLC 地址映射与参数配置

四阶段 SAC 模型当前固定为：

| 阶段 | 模型目录                         |
| ---- | -------------------------------- |
| INI  | `rl_models/ini_20260614_231157`  |
| DEV  | `rl_models/dev_20260614_234632`  |
| MID  | `rl_models/mid_20260615_003559`  |
| LATE | `rl_models/late_20260615_005859` |

## 5. 当前研究完成度判断

| 模块                | 当前状态             | 论文可用性           |
| ------------------- | -------------------- | -------------------- |
| 数字孪生仿真环境    | 已完成基础版         | 可作为模型章节       |
| 四阶段 SAC 模型     | 已固定基线           | 可作为智能决策章节   |
| PLC 通信 DB1        | 已完成               | 可作为系统实现章节   |
| PLC 编译状态        | 成功，0 错误 0 警告  | 可作为工程验证依据   |
| PLC 前馈 + 模糊 PID | 已完成               | 可作为执行层控制方法 |
| PLC 在环环境        | 已具备               | 可作为实验验证章节   |
| 真实硬件接入        | 未完全完成           | 放后续实验或展望     |
| ESO-AFOPID          | 未实现               | 放扩展研究           |
| EnKF 数据同化       | 未实现               | 放扩展研究           |
| OPC UA 通信         | 未实现，当前为 Snap7 | 不作为近期主线       |

## 6. 更新后的后续研究流程

后续研究不再优先开发 Web 端，重点转为论文主线实验和 PLC 在环验证。

### 阶段一：PLC 与上位机基线固化

目标：保证当前 PLC 与四阶段 SAC 模型成为稳定实验基线。

任务：

1. 固定 `DB1` 地址映射，不再随意改 offset。
2. 固定四阶段 SAC 模型目录。
3. 固定 PLC SCL 源码与数字孪生镜像同步规则。
4. 每次 PLC 修改后执行 Openness 编译检查。
5. 记录编译结果和块清单作为实验环境说明。

产出：

- PLC 工程状态快照
- 通信变量表
- 上位机-PLC 数据流说明

### 阶段二：离线数字孪生实验

目标：先证明 SAC 在数字孪生环境中优于固定策略。

任务：

1. 跑固定策略 vs SAC 单阶段对比。
2. 分别评价 INI、DEV、MID、LATE 四阶段。
3. 统计根区 EC 误差、出口 EC/pH 误差、q_f/q_a 执行量。
4. 输出曲线图和指标表。

产出：

- 四阶段对比实验图
- 固定策略与 SAC 指标表
- 奖励函数与控制效果分析

### 阶段三：全生育期阶段切换实验

目标：证明四阶段 SAC 模型能够覆盖马铃薯完整生长周期。

任务：

1. 按生育期自动切换四个 SAC 模型。
2. 跑全生育期数字孪生仿真。
3. 分析阶段切换时 EC/pH 目标变化是否平滑。
4. 分析总灌溉量、水肥利用效率和盐分控制效果。

产出：

- 全生育期 EC/pH 曲线
- 阶段切换控制曲线
- 水肥利用与安全性指标

### 阶段四：PLC/PLCSIM 在环验证

目标：证明 PLC 执行层能把上位机目标稳定转化为执行流量。

任务：

1. 使用 `run_hil.py` 做单阶段 PLC 在环测试。
2. 使用 `run_full_season_plc.py` 做压缩全生育期 PLC 在环测试。
3. 记录 PLC 输出 `q_f_cmd/q_a_cmd/q_n_cmd/q_p_cmd/q_k_cmd`。
4. 验证通信看门狗、目标保护、限幅限速是否有效。
5. 对比纯仿真执行层与 PLC 执行层差异。

产出：

- PLC 在环时序数据
- PLC 执行层误差分析
- 安全保护触发记录

### 阶段五：论文方法整理

目标：把工程系统整理成研究生论文方法体系。

建议论文主线：

```text
数字孪生建模
    ↓
四阶段 SAC 智能决策
    ↓
PLC 前馈-模糊 PID 安全执行
    ↓
离线仿真与 PLCSIM 在环验证
```

章节建议：

1. 绪论
2. 马铃薯水肥一体化数字孪生模型
3. 基于 SAC 的阶段化水肥目标决策方法
4. PLC 底层安全执行控制系统设计
5. 仿真与 PLC 在环实验结果分析
6. 总结与展望

### 阶段六：可选增强研究

基础论文闭环完成后，再考虑增强项：

1. 动态 PID 参数下发：上位机输出 `EC_set/pH_set/Kp/Ki`。
2. ESO-AFOPID：替换或增强当前模糊 PID。
3. OPC UA：替代 Snap7，提升工业通信规范性。
4. EnKF 数据同化：接入真实传感器后做数字孪生在线校正。
5. 真实电路与硬件：接入传感器、模拟量模块、变频器和实际泵阀。

## 7. 近期最优先任务

建议接下来按这个顺序推进：

1. 跑一次四阶段 SAC 模型离线对比实验。
2. 跑一次全生育期 SAC 阶段切换实验。
3. 跑一次 PLC/PLCSIM 单阶段 HIL 测试。
4. 跑一次 PLC/PLCSIM 全生育期压缩测试。
5. 汇总 4 类实验图和指标表。
6. 将 PLC 编译快照、DB1 通信表和实验结果写入开题/中期材料。

这条路线最适合当前研究生论文：风险低、闭环完整、结果可解释，也能自然承接后续 ESO-AFOPID 和硬件电路设计。

