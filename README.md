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
主水泵建立 q_w_actual，输出 q_f、q_a
        ↓
混合罐模型 → 管道滞后模型 → 根区水盐模型
        ↓
更新土壤含水率、土壤 EC、出口 EC、出口 pH
```

其中：

```text
SAC 负责：决定目标 EC 和目标 pH
PID/PLC 负责：根据 EC/pH 目标和反馈值计算施肥泵、酸泵控制量
灌溉执行层负责：控制主水泵流量/压力、累计水量并建立 Water_Flow_OK 联锁
数字孪生负责：模拟水泵动态、混肥、管道、土壤水盐和作物生育期响应
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
| `water_pump.py` | 主灌溉水泵动态、流量/压力模式、累计水量和无水联锁模型 |
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
| `q_n_cmd` | REAL | PLC → Python | 氮肥通道计量泵输出 |
| `q_p_cmd` | REAL | PLC → Python | 磷肥通道计量泵输出 |
| `q_k_cmd` | REAL | PLC → Python | 钾肥通道计量泵输出 |
| `N_Enable` / `P_Enable` / `K_Enable` | REAL | Python → PLC | 三路肥液通道启用开关，`>=0.5` 表示启用 |
| `N_Ratio` / `P_Ratio` / `K_Ratio` | REAL | Python → PLC | 总肥液流量 `q_f_cmd` 到氮/磷/钾三路的分配比例 |
| `N_Target` / `P_Target` / `K_Target` | REAL | Python → PLC | 根区氮/磷/钾目标值 |
| `N_Actual` / `P_Actual` / `K_Actual` | REAL | Python → PLC | 根区氮/磷/钾反馈值 |
| `Kp_N_Set` / `Ki_N_Set` / `Kd_N_Set` | REAL | Python → PLC | 氮肥通道 PID 参数 |
| `Kp_P_Set` / `Ki_P_Set` / `Kd_P_Set` | REAL | Python → PLC | 磷肥通道 PID 参数 |
| `Kp_K_Set` / `Ki_K_Set` / `Kd_K_Set` | REAL | Python → PLC | 钾肥通道 PID 参数 |
| `N_Max` / `P_Max` / `K_Max` | REAL | Python → PLC | 三路计量泵最大流量限幅 |
| `Valve_F_Actual` | REAL | PLC → Python | 施肥阀实际开度 |
| `Valve_A_Actual` | REAL | PLC → Python | 酸阀实际开度 |
| `AQ_Valve_F_Raw` | INT | PLC → Python | 施肥模拟量输出原始值 |
| `AQ_Valve_A_Raw` | INT | PLC → Python | 酸液模拟量输出原始值 |
| `AQ_Valve_N_Raw` / `AQ_Valve_P_Raw` / `AQ_Valve_K_Raw` | INT | PLC → Python | 氮/磷/钾三路模拟量输出原始值 |
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

多肥液版本中，PLC 还保留三路 N/P/K 微调 PID。默认情况下，总肥液需求由 EC_PID 给出：

```text
q_f_cmd = EC_PID(EC_Set_SP, EC_Actual)
```

然后 PLC 按比例分配到三路肥液：

```text
q_n_cmd = q_f_cmd * N_Ratio + N_PID(N_Target, N_Actual)
q_p_cmd = q_f_cmd * P_Ratio + P_PID(P_Target, P_Actual)
q_k_cmd = q_f_cmd * K_Ratio + K_PID(K_Target, K_Actual)
```

如果没有在线 N/P/K 传感器，三路 PID 参数可以先保持为 0，只用 `N_Ratio/P_Ratio/K_Ratio` 做配方分配。换肥料时优先改配方比例和通道启用状态，不需要改 PLC 主程序。

注意：DB 块需要关闭“优化的块访问”，否则 Snap7 可能无法按偏移地址读写。

---

## 13. Python 与 PLCSIM 在环仿真

`plc_gym_env.py` 已经按 B 方案改好。

当前数据流为：

```text
Agent action [EC_set, pH_set]
        ↓
Python 写入 PLC/PLCSIM：
EC_Set_SP、pH_Set_SP、EC_Actual、pH_Actual、
N_Target/P_Target/K_Target、N_Actual/P_Actual/K_Actual
        ↓
PLC/PLCSIM 内部执行：
EC-PID → q_f_cmd
pH-PID → q_a_cmd
N/P/K 分配与微调 PID → q_n_cmd、q_p_cmd、q_k_cmd
        ↓
Python 回读 q_f_cmd、q_a_cmd、q_n_cmd、q_p_cmd、q_k_cmd
        ↓
混合罐 + 管道滞后 + 根区水盐/NPK 模型继续推进田间状态
```

当前 PLC 在环版本已经加入多肥液和混合肥料仿真：

1. `q_f_cmd` 表示总肥液需求，由 EC_PID 根据 EC 目标和反馈计算。
2. `q_n_cmd/q_p_cmd/q_k_cmd` 表示氮、磷、钾三路肥液计量泵输出。
3. Python 侧数字孪生把水、总肥液、酸液送入 `mixing_tank.py`，得到混合肥液 EC 和 pH。
4. 混合后的 EC/pH 再经过 `pipe_dynamics.py` 的管道滞后，进入根区模型。
5. `plc_gym_env.py` 内部用轻量根区 N/P/K 估算模型记录 `n_actual/p_actual/k_actual`，并与 `n_target/p_target/k_target` 对比画图。
6. `experiments/plot_plc_npk_ec_ph.py` 会输出 `npk_ec_ph_execution.png`，同时显示 EC、pH、N/P/K 和 PLC 各泵执行量。

为了让压缩生命周期仿真更接近真实部署，当前还加入了四项处理：

1. 短阶段过渡：`experiments/run_full_season_plc.py` 的 `--transition-days` 默认改为 `5`。INI/DEV/MID/LATE 阶段内保持稳定目标，只在换阶段后的短窗口平滑过渡，避免硬阶跃冲击；PLC 端已加大目标变化阈值，不会再因为连续小步变化反复清积分。
2. PLC 手动测试下限：手动 PLC 在环测试允许 EC 给定低于 SAC 训练下限 `0.8`，第一阶段可以使用 `0.75` 这类补偿值，不会再被 Python 或 `PLCGymEnv` 夹回 `0.8`。
3. 根区 EC 观测缓冲：`plc_gym_env.py` 保留土壤模型原始输出 `raw_ec_soil`，同时生成更接近传感器读数的 `ec_soil`。在目标明显下调并正在灌溉时，压缩仿真允许更强的冲洗响应，避免上一阶段高 EC 在根区模型中滞留过久。
4. 酸泵平稳化：pH 反馈写入 PLC 前使用更强低通滤波，PLC SCL 中加大 pH 死区与滤波时间常数，目标附近维持酸液前馈并收紧酸泵斜坡限速，减少 `q_a_cmd` 在目标附近来回跳动。

全生命周期 PLC 在环测试示例：

```powershell
cd "D:\Digital Twin"

D:\Miniconda3\python.exe .\plc\tuning\write_pid_to_plc.py `
  --kp-ec 1.05 --ki-ec 0.0100 --kd-ec 0.036 `
  --kp-ph 3.65 --ki-ph 0.034 --kd-ph 0.016

D:\Miniconda3\python.exe .\experiments\run_full_season_plc.py `
  --manual-test `
  --season-days 110 `
  --steps 720 `
  --plc-wait-s 0.03 `
  --transition-days 6 `
  --fixed-ini-ec 0.75 --fixed-ini-ph 6.172 `
  --fixed-dev-ec 1.115 --fixed-dev-ph 6.068 `
  --fixed-mid-ec 1.445 --fixed-mid-ph 5.856 `
  --fixed-late-ec 0.928 --fixed-late-ph 6.072 `
  --ph-down-transition-days 3
```

`--transition-days 6` 表示只在阶段切换后的 6 天内平滑过渡。它不是全生命周期不断趋近目标，而是用短过渡减少 EC/pH 阶跃冲击；如果要做硬切换，可以改成 `--transition-days 0`。

当前这组参数在 110 天、720 步 PLC 在环测试中得到：

```text
EC_MAE=0.011066
pH_MAE=0.008396
N_MAE=0.038497
P_MAE=0.021650
K_MAE=0.049957
```

本轮更稳版本保留结果目录：

```text
results/full_season_plc/20260614_104834/
```

与硬切换版本相比，EC 最大单步跳变约从 `0.237` 降到 `0.096`，pH MAE 降到约 `0.0084`，酸泵 `q_a_cmd` 平均相邻步跳变约从 `0.0455 L/min` 降到约 `0.0027 L/min`，适合作为当前默认稳定参数。

运行结果会保存到：

```text
results/full_season_plc/<run_id>/
```

其中：

```text
full_season_plc_timeseries.csv：完整时序数据，包含 ec_soil、raw_ec_soil、pH、N/P/K、各泵输出
npk_ec_ph_execution.png：N/P/K、EC、pH 和 PLC 执行量效果图
soil_ec_ph_by_day.png：日均 EC/pH 运行图
summary.json：运行参数和最终状态
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
