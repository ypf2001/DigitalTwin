# PLC 现场验收表

软件阶段保持 `Deployment_Mode=0`、`Actuator_Enable_Request=FALSE`。以下项目全部签字通过前，不得授权真实输出。

| Item | Method | Acceptance | Result | Sign-off |
|---|---|---|---|---|
| Point-to-point I/O | Inject/operate every AI, HSC, DI, AO and DO | Tag, polarity and destination match the I/O list | Pending | |
| 4-20 mA calibration | Apply two traceable points per analog channel | Engineering value within instrument tolerance | Pending | |
| Flow pulse calibration | Run a measured water volume | Pulse K factor recorded and repeatable | Pending | |
| Pump curves | Test water, N, P, K and acid independently | Command-to-flow curve and minimum stable flow recorded | Pending | |
| No-flow interlock | Command each dosing pump without carrier flow | Dosing AO/DO return to zero | Pending | |
| Sensor wire break | Open each critical analog loop | `Sensor_Fault_Any=TRUE`, execution permission drops | Pending | |
| Drive fault | Inject each drive fault | `Drive_Fault_Any=TRUE`, execution permission drops | Pending | |
| Physical E-stop | Operate hardwired E-stop | Contactor/STO removes energy; PLC feedback changes | Pending | |
| Soft stop | Set `Soft_Stop_Request` | All final AO/DO return to zero | Pending | |
| SAC interruption | Stop heartbeat | Remote commands are revoked; PLC performs final stop/limits | Pending | |
| HMI recovery | Disconnect and restore PN connection | Status recovers without an unintended restart | Pending | |
| Clean-water run | Run carrier water only | Stable pressure/flow, no dosing output | Pending | |
| Single-channel water test | Enable one metering pump with water | Correct channel only; flow and alarms verified | Pending | |

真实肥料和酸液投料不属于本阶段验收范围。
