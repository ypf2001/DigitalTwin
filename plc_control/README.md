# PLC 调控模块

本模块负责通过 Snap7 对 PLC/PLCSIM 进行实时监控和控制。TIA Portal 工程读取、块导入、编译、保存和下载已迁移到 `tia_portal` MCP，不再由 Python 直接加载 Siemens Openness API。

## 模块结构

```text
plc_control/
|-- controller.py       # PLC 实时控制器 (Snap7)
|-- control_panel.py    # 上位机实时控制面板
|-- gain_schedule.py    # 增益调度
|-- imc_smith.py        # IMC/Smith 控制
|-- mimo_fopdt.py       # MIMO FOPDT 模型
`-- ab_validation.py    # 控制策略验证
```

## 实时控制

```python
from plc_control.controller import PLCController, ControlMode

with PLCController(ip="127.0.0.1") as ctrl:
    state = ctrl.read_state()
    print(f"EC: {state.ec_actual}, pH: {state.ph_actual}")

    ctrl.set_control_mode(ControlMode.AUTO_REMOTE)
    ctrl.set_setpoints(ec=1.8, ph=6.2)
    ctrl.set_growth_stage(2)
    ctrl.set_npk_ratios(n=0.35, p=0.25, k=0.40)
```

## 控制面板

```powershell
python -m plc_control.control_panel
```

控制面板只负责 PLC 运行时通信。需要查看或修改 TIA 工程时，在 Codex 中使用 `$tia-portal-openness` 和 `tia_portal` MCP。

## 依赖

- Python 3.8+
- `python-snap7`

## 注意事项

1. 确保通信 DB 关闭优化块访问。
2. PLCSIM/真实 PLC 的 IP、Rack、Slot 必须与配置一致。
3. 工程写入后必须通过 MCP 编译并保存；下载前执行 MCP 的下载就绪检查。
