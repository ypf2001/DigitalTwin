# 河套土壤 Fluent 填参表

这些参数是内蒙古河套灌区土壤水盐运移的论文初值，用于先把 Fluent 土柱模型跑起来。真实部署前需要用实测入流、出流 EC 曲线再校准一次。

## 几何命名

| Fluent 名称 | 位置 | 类型 |
| --- | --- | --- |
| soil | 圆柱体积区域 | porous fluid zone |
| inlet | 土柱顶部圆面，X = 500 mm | velocity-inlet 或 mass-flow-inlet |
| outlet | 土柱底部圆面，X = 0 mm | pressure-outlet |
| wall | 圆柱侧壁，半径 50 mm | wall |

3D 圆柱不需要 axis 边界；axis 只用于 2D 轴对称模型。

## Cell Zone Conditions > soil > Porous Zone

| 参数 | Fluent 输入值 | 单位 |
| --- | ---: | --- |
| Porosity | 0.42 | - |
| Viscous Resistance X | 5.513e13 | 1/m2 |
| Viscous Resistance Y | 5.513e13 | 1/m2 |
| Viscous Resistance Z | 5.513e13 | 1/m2 |
| Inertial Resistance X/Y/Z | 0 | 1/m |

上表按各向同性土壤先跑。如果后续实测显示竖向渗透明显强于径向，可以只调竖向对应方向的 viscous resistance。

## Species / 盐分输运

| 参数 | Fluent 输入值 | 单位 |
| --- | ---: | --- |
| 分子扩散系数 | 8.102e-10 | m2/s |
| 弥散度 | 0.05 | m |
| 初始土壤 EC | 0.15 | dS/m |

Fluent 标准 species diffusion 能直接填分子扩散系数；弥散度通常需要用 UDF 或等效扩散系数表示。第一版可先只用分子扩散系数验证流场和延迟，再加入弥散项。

## 单位换算

- K_sat = 15.3 mm/d = 1.771e-7 m/s
- intrinsic permeability = K_sat * mu / (rho * g) = 1.814e-14 m2
- viscous resistance = 1 / permeability = 5.513e13 1/m2
- 0.7 cm2/d = 8.102e-10 m2/s

