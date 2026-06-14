# Fluent 土壤溶液渗透模型

本模型用于把当前项目的 PLC/Python 水肥闭环结果接入 Fluent，做根区土壤溶液渗透与 EC、N/P/K 运移分析。

## 1. 模型定位

当前 Python 数字孪生中的 `soil_transport.py` 是集总根区模型，适合快速训练 SAC 和 PLC 在环闭环测试。Fluent 模型用于更细的空间分布分析：

```text
PLC/Python full_season_plc_timeseries.csv
        -> scripts/export_fluent_soil_boundary.py
        -> fluent/fluent_soil_boundary.csv
        -> Fluent porous soil + UDS transport
        -> 根区 EC/N/P/K 空间分布、深层渗漏、湿润锋扩散
```

## 2. Fluent 建模建议

几何可以先用 2D 轴对称根区剖面：

```text
半径: 0.30~0.50 m
深度: 0.60~1.00 m
滴灌入口: 顶部中心 0.02~0.05 m 宽
底部: pressure-outlet 或 outflow
侧边: wall / symmetry
土体: porous zone
```

物理模型：

```text
Solver: pressure-based, transient
Flow: laminar
Material: liquid water
Cell zone: porous media
UDS: 4 个
  UDS-0 = EC 等效溶质
  UDS-1 = N
  UDS-2 = P
  UDS-3 = K
```

多孔介质阻力先按 Darcy 量级给定，后续可用实测入渗曲线校准：

```text
permeability K = 1e-11 ~ 1e-10 m2
viscous resistance = 1 / K
inertial resistance = 0
porosity = 0.42
```

## 3. 从本项目导出 Fluent 边界

先跑 PLC 全生命周期或已有结果目录，然后导出边界：

```powershell
cd "D:\Digital Twin"

D:\Miniconda3\python.exe .\scripts\export_fluent_soil_boundary.py `
  .\results\full_season_plc\20260612_231225 `
  --output .\fluent\fluent_soil_boundary.csv
```

输出 CSV 字段：

```text
time_s              Fluent 时间，秒
irrigation_mm_h     灌溉强度，mm/h
ec_drip             滴灌入口 EC
n_drip              N 入口等效浓度
p_drip              P 入口等效浓度
k_drip              K 入口等效浓度
```

## 4. UDF 挂接位置

编译 `fluent/soil_solution_percolation_udf.c` 后，在 Fluent 中挂接：

```text
Velocity inlet:
  velocity magnitude -> drip_velocity_profile

UDS boundary conditions:
  UDS-0 inlet value -> drip_ec_uds0_profile
  UDS-1 inlet value -> drip_n_uds1_profile
  UDS-2 inlet value -> drip_p_uds2_profile
  UDS-3 inlet value -> drip_k_uds3_profile

UDS diffusivity:
  soil_solution_diffusivity

UDS source terms:
  UDS-0 -> ec_root_sink
  UDS-1 -> n_root_sink
  UDS-2 -> p_root_sink
  UDS-3 -> k_root_sink
```

## 5. 与项目变量的对应关系

```text
Python/PLC q_f_cmd        -> 总肥液需求
Python/PLC q_n/q_p/q_k    -> N/P/K 三路计量泵输出
Python ec_drip            -> Fluent UDS-0 入口
Python irrigation_mm_h    -> Fluent 入口速度
Python ec_soil            -> Fluent 根区平均 UDS-0 对比量
Python raw_ec_soil        -> 原始集总土壤模型输出，仅用于诊断
```

## 6. 校准顺序

1. 先只开水流，不开 UDS，校准湿润锋深度和底部出流。
2. 开 UDS-0，调 `soil_solution_diffusivity` 中的 `dispersivity`，让根区平均 EC 接近 Python 的 `ec_soil`。
3. 再开 UDS-1/2/3，调 `nutrient_sink_rate`，让根区平均 N/P/K 接近 Python 的 `n_actual/p_actual/k_actual`。
4. 最后用 Fluent 输出的根区平均值反向替代 Python 的集总 `soil_transport.py`，用于高保真验证，不建议直接用于 SAC 快速训练。

## 7. 结果输出建议

在 Fluent 里建立 surface/volume report：

```text
root_zone_avg_ec: 根区 0~0.30 m 体积平均 UDS-0
deep_leaching_ec: 底部出口 UDS-0 通量
root_zone_avg_n/p/k: 根区 N/P/K 体积平均
wetting_front: 含水率或速度等值线前缘
```

这些结果可以和 `results/full_season_plc/<run_id>/full_season_plc_timeseries.csv` 对比，用来判断 PLC 策略在真实空间土壤中的局部积盐风险。
