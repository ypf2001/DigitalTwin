# 马铃薯水肥一体化数字孪生与 SAC-PID 分层控制系统

本仓库用于构建马铃薯滴灌水肥一体化数字孪生仿真平台，并实现基于 Soft Actor-Critic（SAC）的上层智能决策与 PLC/PID 底层执行控制。

当前主线已经从原来的 **A 方案：SAC 直接输出泵阀执行量**，改为 **B 方案：SAC 输出 EC/pH 目标值，PID/PLC 执行层输出泵阀控制量**。

---

## 1. 当前控制架构

当前推荐架构为：

```text
田间传感器 / 数字孪生状态
        ↓
上位机 SAC 智能决策
        ↓
输出 EC_set、pH_set
        ↓
PLC / PLCSIM / 仿真执行层 PID
        ↓
输出 q_f、q_a
        ↓
混合罐模型 → 管道滞后模型 → 根区水盐模型
        ↓
更新土壤含水率、土壤 EC、出口 EC、出口 pH
```

其中：

```text
SAC 负责：决定目标 EC 和目标 pH
PID/PLC 负责：根据 EC/pH 目标和反馈值计算施肥泵、酸泵控制量
数字孪生负责：模拟混肥、管道、土壤水盐和作物生育期响应
```

---

## 2. 与原来 A 方案的区别

### 原来 A 方案

原来的代码逻辑是：

```text
SAC action = [q_f, q_a]
```

也就是 SAC 直接输出：

```text
q_f：母液流量 / 施肥泵流量
q_a：酸液流量 / 酸泵流量
```

控制流程为：

```text
SAC → q_f、q_a → MixingTank → PipeDynamics → SoilTransport
```

这种方式代码简单，但工程上相当于 SAC 直接控制泵阀，安全性和可解释性较弱。

### 现在 B 方案

现在代码逻辑改为：

```text
SAC action = [EC_set, pH_set]
```

也就是 SAC 只输出上层目标：

```text
EC_set：滴灌液 / 混肥出口目标 EC
pH_set：滴灌液 / 混肥出口目标 pH
```

然后由执行层计算：

```text
q_f：母液流量 / 施肥泵流量
q_a：酸液流量 / 酸泵流量
```

控制流程变为：

```text
SAC → EC_set、pH_set → PID/执行层 → q_f、q_a → 数字孪生模型
```

B 方案更适合论文表述为：

```text
基于数字孪生与 SAC-PID 分层控制的马铃薯水肥一体化调控方法
```

---

## 3. 关键文件说明

| 文件 | 作用 |
|---|---|
| `digital_twin_env.py` | 数字孪生核心环境，当前动作输入为 `[EC_set, pH_set]` |
| `digital_twin_gym_env.py` | Gymnasium 封装，用于 SAC 训练 |
| `setpoint_controller.py` | 纯仿真执行层，将 `EC_set/pH_set` 转换为 `q_f/q_a` |
| `mixing_tank.py` | 混肥罐 EC/pH 估算模型 |
| `pipe_dynamics.py` | 管道纯滞后 + 一阶惯性模型 |
| `soil_transport.py` | 根区水分-盐分集总模型 |
| `crop_model.py` | 马铃薯生育期、ETc、目标 EC、根深模型 |
| `train_sac.py` | SAC 训练脚本 |
| `eval_sac.py` | SAC-PID 全生育期评估脚本 |
| `irrigation_schedule.py` | T1/T2 灌溉制度仿真 |
| `plc_client.py` | Python 与 PLC/PLCSIM 通信客户端 |
| `plc_gym_env.py` | PLC/PLCSIM 在环仿真环境 |
| `web_app/backend/app.py` | FastAPI 后端入口 |
| `web_app/backend/services.py` | Web 仿真、配置、训练和模型管理逻辑 |

---

## 4. 配置文件变化

主要配置在：

```text
config/simulation.yaml
```

当前动作空间为：

```yaml
action:
  ec_set_min: 0.8
  ec_set_max: 2.5
  ph_set_min: 5.8
  ph_set_max: 6.8

  q_f_min: 0.0
  q_f_max: 10.0
  q_a_min: 0.0
  q_a_max: 4.0

  fixed_strategy:
  - 1.5
  - 6.0
```

含义：

```text
ec_set_min / ec_set_max：SAC 输出 EC_set 的范围
ph_set_min / ph_set_max：SAC 输出 pH_set 的范围
q_f_min / q_f_max：执行层施肥流量限幅
q_a_min / q_a_max：执行层酸液流量限幅
fixed_strategy：[固定 EC_set, 固定 pH_set]
```

注意：`fixed_strategy` 现在不是 `[q_f, q_a]`，而是 `[EC_set, pH_set]`。

---

## 5. 安装依赖

建议使用 Python 3.10 或 3.11。

```bash
pip install -r requirements.txt
```

常用依赖包括：

```text
numpy
stable-baselines3
torch
gymnasium
matplotlib
pyyaml
python-snap7
fastapi
uvicorn
pymysql
```

---

## 6. 快速验证代码是否能跑

建议先用很小步数验证环境和训练链路：

```bash
python train_sac.py --stage MID --timesteps 1000 --fresh
```

如果 1000 步能正常运行，再进行正式训练。

---

## 7. 重新训练 SAC

由于动作空间已经从 `[q_f, q_a]` 改为 `[EC_set, pH_set]`，旧模型不再适用，必须重新训练。

单阶段训练：

```bash
python train_sac.py --stage MID --timesteps 120000 --fresh
```

四个阶段分别训练：

```bash
python train_sac.py --stage INI  --timesteps 120000 --fresh
python train_sac.py --stage DEV  --timesteps 120000 --fresh
python train_sac.py --stage MID  --timesteps 120000 --fresh
python train_sac.py --stage LATE --timesteps 120000 --fresh
```

训练完成后，模型一般保存在：

```text
rl_models/sac_ini_final.zip
rl_models/sac_dev_final.zip
rl_models/sac_mid_final.zip
rl_models/sac_late_final.zip
```

---

## 8. 评估 SAC-PID 控制效果

运行：

```bash
python eval_sac.py --dt-min 15 --et0 4.0
```

评估脚本会记录：

```text
EC_set
pH_set
q_f
q_a
ec_drip
ph_drip
theta
ec_soil
irrigation_mm_h
etc_mm_h
```

重点查看：

```text
EC_set 是否在 0.8~2.5 dS/m 范围内
pH_set 是否在 5.8~6.8 范围内
q_f / q_a 是否长期打满
根区 EC MAE 是否降低
是否触发 burn / hard penalty
```

输出图像保存在：

```text
pic_output/eval_sac/
```

---

## 9. 运行 T1/T2 灌溉制度对比

运行批处理实验：

```bash
python experiments/run_simulation_suite.py
```

输出内容包括：

```text
短期固定目标仿真
90 天 T1/T2 灌溉制度对比
CSV 时序数据
JSON 指标汇总
PNG 图表
```

输出目录一般为：

```text
results/simulation_suite/
experiments/images/simulation_suite/
```

---

## 10. 启动 Web 后端

进入后端目录：

```bash
cd web_app/backend
python app.py
```

默认地址：

```text
http://localhost:5000
```

常用接口：

```text
GET  /api/config
POST /api/simulate
POST /api/season-compare
GET  /api/training/status
POST /api/training/start
POST /api/training/stop
GET  /api/training/models
```

短时仿真返回数据中，当前已经区分：

```text
EC_set / pH_set：SAC 上层目标值
q_f / q_a：执行层输出流量
ec_drip / ph_drip：出口反馈值
theta / ec_soil：根区田间状态
```

---

## 11. 使用 PLCSIM / PLCSIM Advanced 做执行层

如果不用真实 PLC，可以用电脑上的 TIA Portal + PLCSIM / PLCSIM Advanced 代替真实执行层。

推荐流程：

```text
Python 数字孪生 / SAC
        ↓
写入 PLCSIM DB：EC_Set_SP、pH_Set_SP、EC_Actual、pH_Actual
        ↓
PLCSIM 中 PLC-PID 计算 q_f_cmd、q_a_cmd
        ↓
Python 读取 q_f_cmd、q_a_cmd
        ↓
数字孪生模型继续推进田间状态
```

这可以称为：

```text
基于 PLCSIM 的 PLC 在环仿真
```

或：

```text
上位机智能决策与 PLC 底层控制的半实物仿真验证
```

---

## 12. 推荐 PLC DB 变量表

当前 `config/simulation.yaml` 中建议 DB 变量如下：

| 变量名 | 类型 | 方向 | 含义 |
|---|---|---|---|
| `EC_Set_SP` | REAL | Python → PLC | SAC 输出目标 EC |
| `pH_Set_SP` | REAL | Python → PLC | SAC 输出目标 pH |
| `EC_Actual` | REAL | Python → PLC | 数字孪生或传感器反馈 EC |
| `pH_Actual` | REAL | Python → PLC | 数字孪生或传感器反馈 pH |
| `SAC_Enable` | BOOL | Python → PLC | SAC/远程模式使能 |
| `Remote_Heartbeat` | INT | Python → PLC | 上位机心跳 |
| `Remote_Comms_OK` | BOOL | PLC → Python | PLC 判断通信正常 |
| `Watchdog_Timer` | INT | PLC → Python | 看门狗计数 |
| `q_f_cmd` | REAL | PLC → Python | 施肥泵 / 母液流量输出 |
| `q_a_cmd` | REAL | PLC → Python | 酸泵 / 酸液流量输出 |
| `Valve_F_Actual` | REAL | PLC → Python | 施肥阀实际开度 |
| `Valve_A_Actual` | REAL | PLC → Python | 酸阀实际开度 |
| `AQ_Valve_F_Raw` | INT | PLC → Python | 施肥模拟量输出原始值 |
| `AQ_Valve_A_Raw` | INT | PLC → Python | 酸液模拟量输出原始值 |
| `System_Alarm_Light` | BOOL | PLC → Python | 系统报警 |

PLC 中建议建立两个 PID：

```text
EC_PID：
SP = EC_Set_SP
PV = EC_Actual
OUT = q_f_cmd

pH_PID：
SP = pH_Set_SP
PV = pH_Actual
OUT = q_a_cmd
```

注意：DB 块需要关闭“优化的块访问”，否则 Snap7 可能无法按偏移地址读写。

---

## 13. Python 与 PLCSIM 在环仿真

`plc_gym_env.py` 已经按 B 方案改好。

当前数据流为：

```text
Agent action [EC_set, pH_set]
        ↓
Python 写入 PLC/PLCSIM：EC_Set_SP、pH_Set_SP、EC_Actual、pH_Actual
        ↓
PLC/PLCSIM 内部 EC-PID、pH-PID 计算 q_f_cmd、q_a_cmd
        ↓
Python 回读 q_f_cmd、q_a_cmd
        ↓
数字孪生模型推进田间状态
```

使用时需要：

```text
1. 打开 TIA Portal 工程
2. 创建并下载 DB 块
3. 关闭 DB 块优化访问
4. 启动 PLCSIM / PLCSIM Advanced
5. 确认 IP、Rack、Slot 和 config/simulation.yaml 中一致
6. 再运行 Python 侧 PLCGymEnv 或相关测试脚本
```

---

## 14. 论文中推荐表述

可以写成：

> 系统采用“上位机智能决策—PLC 实时执行”的分层控制架构。上位机运行数字孪生模型与 SAC 强化学习算法，根据根区水盐状态、滴灌出口 EC/pH 及马铃薯生育期状态输出滴灌液 EC 和 pH 目标值；PLC 作为底层控制器，根据 EC/pH 目标值与反馈值运行 PID 控制器，计算施肥泵和酸泵控制量，并通过泵阀执行机构完成水肥调控。当上位机通信异常或目标值超限时，PLC 自动切换至本地 PID 或固定设定值控制模式，以保证系统安全运行。

---

## 15. 当前阶段建议

现在建议按以下顺序推进：

```text
第一步：用 1000 步训练验证代码无语法错误
第二步：重新训练 MID 阶段 SAC
第三步：运行 eval_sac.py 看 EC_set/pH_set 和 q_f/q_a 是否合理
第四步：训练 INI/DEV/MID/LATE 四阶段模型
第五步：在博途中建立 DB 和 EC_PID、pH_PID
第六步：用 PLCSIM 做 PLC 在环仿真
第七步：再接真实 PLC、传感器和泵阀
```

---

## 16. 注意事项

1. 旧 SAC 模型不能直接用于当前 B 方案，因为动作空间已经改变。
2. `fixed_strategy` 已由 `[q_f, q_a]` 改为 `[EC_set, pH_set]`。
3. 纯 Python 仿真时，`setpoint_controller.py` 模拟执行层。
4. PLCSIM 在环仿真时，博途里的 PID 才是真正执行层。
5. 真实田间运行时，PLC 应保留本地 PID 和安全联锁，不能完全依赖上位机。
