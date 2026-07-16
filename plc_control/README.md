# PLC 调控模块

本模块提供对 TIA Portal 项目和 PLC 的完整调控能力。

## 模块结构

```
plc_control/
├── __init__.py          # 模块入口
├── project_reader.py    # TIA 项目读取器 (Openness API)
├── controller.py        # PLC 实时控制器 (Snap7)
├── control_panel.py     # 上位机控制面板
└── README.md            # 说明文档
```

## 功能概览

### 1. 项目读取 (project_reader.py)

使用 TIA Portal Openness API 读取项目内容：

```python
from plc_control.project_reader import TIAProjectReader

# 打开项目
with TIAProjectReader(r"D:\dw_plc\xiaweiji\xiaweiji.ap21") as reader:
    # 列出 PLC
    plcs = reader.list_plcs()
    
    # 列出程序块
    blocks = reader.list_blocks()
    
    # 列出标签表
    tables = reader.list_tag_tables()
    
    # 编译 PLC
    result = reader.compile_plc()
```

### 2. 实时控制 (controller.py)

通过 Snap7 与 PLC 实时通信：

```python
from plc_control.controller import PLCController, ControlMode

# 连接 PLC
with PLCController(ip="127.0.0.1") as ctrl:
    # 读取状态
    state = ctrl.read_state()
    print(f"EC: {state.ec_actual}, pH: {state.ph_actual}")
    
    # 设置控制模式
    ctrl.set_control_mode(ControlMode.AUTO_REMOTE)
    
    # 设置目标值
    ctrl.set_setpoints(ec=1.8, ph=6.2)
    
    # 设置生长阶段
    ctrl.set_growth_stage(2)  # MID 阶段
    
    # 设置 NPK 配比
    ctrl.set_npk_ratios(n=0.35, p=0.25, k=0.40)
```

### 3. 控制面板 (control_panel.py)

交互式上位机控制：

```bash
# 启动交互模式
python -m plc_control.control_panel
```

或编程方式：

```python
from plc_control.control_panel import PLCControlPanel

panel = PLCControlPanel()

# 打开项目
panel.open_project()

# 连接 PLC
panel.connect_plc()

# 显示状态
panel.print_status()

# 设置目标值
panel.set_setpoints(ec=1.5, ph=6.0)

# 运行监控
panel.run_monitoring(interval=1.0, count=10)

# 运行控制测试
panel.run_control_test()
```

## PLC 通信协议

### DB1 通信变量

| 变量名 | 偏移 | 类型 | 说明 |
|--------|------|------|------|
| EC_Set_SP | 0 | REAL | SAC 输出目标 EC |
| pH_Set_SP | 4 | REAL | SAC 输出目标 pH |
| EC_Actual | 8 | REAL | 传感器反馈 EC |
| pH_Actual | 12 | REAL | 传感器反馈 pH |
| SAC_Enable | 16.0 | BOOL | 远程自动使能 |
| Remote_Heartbeat | 18 | INT | 心跳计数 |
| Remote_Comms_OK | 20.0 | BOOL | 通信正常标志 |
| q_f_cmd | 24 | REAL | 肥料总流量输出 |
| q_a_cmd | 28 | REAL | 酸液流量输出 |
| q_n_cmd | 182 | REAL | N 肥流量输出 |
| q_p_cmd | 222 | REAL | P 肥流量输出 |
| q_k_cmd | 262 | REAL | K 肥流量输出 |

### 控制模式

- **Manual**: 手动模式，直接设置泵阀输出
- **Auto_Local**: 本地自动，使用阶段配方
- **Auto_Remote**: 远程自动，SAC/AI 控制

## 与 SAC 集成

```python
from plc_control.controller import PLCController, ControlMode

def sac_control_loop(sac_agent, controller):
    """SAC 控制循环"""
    controller.set_control_mode(ControlMode.AUTO_REMOTE)
    
    while running:
        # 读取 PLC 状态
        state = controller.read_state()
        
        # 构建观测
        obs = build_observation(state)
        
        # SAC 推理
        action = sac_agent.act(obs)  # [EC_set, pH_set]
        
        # 写入 PLC
        controller.set_setpoints(
            ec=action[0],
            ph=action[1]
        )
        
        # 更新反馈
        controller.set_feedback(
            ec_actual=state.ec_actual,
            ph_actual=state.ph_actual
        )
```

## 依赖

- Python 3.8+
- snap7
- pythonnet
- Siemens TIA Portal V21 Openness API

## 注意事项

1. **DB 块访问**: 确保 DB1 关闭"优化的块访问"
2. **PLCSIM 连接**: 使用 IP 127.0.0.1
3. **真实 PLC**: 修改 IP 地址为实际设备 IP
4. **TIA Portal**: Openness 操作需要 TIA Portal 运行