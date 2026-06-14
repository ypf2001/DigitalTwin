# PLC 工作区

这个目录集中存放和 PLC 相关的源码快照、说明和后续调参记录。

## 目录

- `xiaweiji/src/xiaweiji.scl`
  - 当前 PLC 程序源码快照。
  - 原始 TIA Portal 工程仍在 `D:\dw_plc\xiaweiji`。
  - 这里的文件用于 GitHub 版本管理和代码审阅。

## 当前工作流程

1. Python 粗调 PID 候选参数

   ```powershell
   cd "D:\Digital Twin"
   .\.venv\Scripts\python.exe .\plc\tuning\tune_pid_coarse.py --mode fixed --trials 80 --season-days 10
   ```

   如果要在 SAC 输出目标的情况下粗调 PID：

   ```powershell
   cd "D:\Digital Twin"
   .\.venv\Scripts\python.exe .\plc\tuning\tune_pid_coarse.py --mode sac --trials 80 --season-days 10
   ```

   输出目录：

   ```text
   D:\Digital Twin\results\pid_tuning\时间戳\
   ```

   主要看：

   ```text
   summary.json
   pid_coarse_results.csv
   ```

2. 从粗调结果里选前几组参数

   粗调结果只是候选值，不是最终 PLC 参数。

   重点看：

   ```text
   score
   ec_mae
   ph_mae
   ec_over_max
   ph_over_max
   flow_move_mean
   ```

3. 把候选参数写入 PLC

   当前 PLC 参数已经放到 `DB1` 的在线调参区：

   ```scl
   Kp_EC_Set
   Ki_EC_Set
   Kd_EC_Set
   Kp_pH_Set
   Ki_pH_Set
   Kd_pH_Set
   ```

   从粗调 `summary.json` 直接写入 PLC：

   ```powershell
   cd "D:\Digital Twin"
   .\.venv\Scripts\python.exe .\plc\tuning\write_pid_to_plc.py `
     --summary ".\results\pid_tuning\时间戳\summary.json"
   ```

   手动写入一组参数：

   ```powershell
   cd "D:\Digital Twin"
   .\.venv\Scripts\python.exe .\plc\tuning\write_pid_to_plc.py `
     --kp-ec 0.8 --ki-ec 0.002 --kd-ec 0.0 `
     --kp-ph 1.2 --ki-ph 0.005 --kd-ph 0.0
   ```

4. PLC/PLCSIM 精调

   每组候选参数用 PLC 跑 5 天或 10 天短仿真，最终以 PLC 跑出来的曲线为准。

5. 最后跑 110 天全生命周期

   ```powershell
   cd "D:\Digital Twin"
   .\.venv\Scripts\python.exe .\experiments\run_full_season_plc.py
   ```

## Openness 编译导入

当前 Openness 工具仍在：

```text
D:\Digital Twin\plc_openness_v21
```

编译导入命令：

```powershell
cd "D:\Digital Twin"
powershell -ExecutionPolicy Bypass -File "D:\Digital Twin\plc_openness_v21\run_import_xiaweiji.ps1"
```

注意：TIA Portal 必须切到离线状态，否则 Openness 会报：

```text
This function is not supported in online mode.
```

## 原则

- Python 粗调：快速筛选范围。
- PLC 精调：确定最终参数。
- 最终论文/结果图：以 PLC/PLCSIM 在环运行结果为准。

## 2026-06-14 PLC 前馈细调窗口

当前推荐分工：

```text
Python 粗调：阶段 EC/pH 目标、N/P/K 配方比例、混合肥料仿真参数
PLC 细调：在前馈流量基础上用 EC/pH PID 做小范围修正
```

SCL 已加入 `EC_Trim_Band` 和 `pH_Trim_Band`：

```text
EC_Trim_Band = 0.10  表示 q_f 只允许在前馈量附近 ±10% 修正
pH_Trim_Band = 0.15  表示 q_a 只允许在前馈量附近 ±15% 修正
```

PLC 内部会把这两个值自动夹在 `0.05~0.15`，也就是只允许 ±5%~±15% 的细调。这样 Python 不再追泵阀细节，PLC 也不会因为 PID 误差把前馈量推得太远。

写入 PID 时可以顺手写入细调窗口：

```powershell
cd "D:\Digital Twin"
.\.venv\Scripts\python.exe .\plc\tuning\write_pid_to_plc.py `
  --kp-ec 1.05 --ki-ec 0.010 --kd-ec 0.036 `
  --kp-ph 3.65 --ki-ph 0.034 --kd-ph 0.016 `
  --ec-trim-band 0.10 --ph-trim-band 0.15
```

注意：`EC_Trim_Band` 和 `pH_Trim_Band` 是 DB1 末尾新增字段，需要把最新 `xiaweiji.scl` 导入/下载到 TIA Portal 或 PLCSIM 后才会在真实 PLC 中生效。

2026-06-14 实测窗口版 PLC 细调结果：

```text
阶段 EC 目标：INI=0.750, DEV=1.115, MID=1.445, LATE=0.928
阶段 pH 目标：INI=6.172, DEV=6.068, MID=5.856, LATE=6.072
EC/常规过渡时间：6 days
pH 下降过渡时间：3 days
EC_Trim_Band=0.10, pH_Trim_Band=0.15
结果目录：D:\Digital Twin\results\full_season_plc\20260614_104834
EC_MAE=0.011066, pH_MAE=0.008396
```
