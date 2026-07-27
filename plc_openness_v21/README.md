# TIA Portal 工程资产

此目录只保留项目生成资产和离线转换工具。原有 Python `pythonnet`/Siemens Openness 调用层已迁移到 `tia_portal` MCP 并删除。

## 保留内容

- `plc_sources/`: SCL 源文件
- `lad_templates/`: LAD/SimaticML 参考资产
- `generated_lad/`: 已生成的 LAD 资产
- `generated_hmi/`: HMI 画面资产
- `examples/`: 不连接 TIA Portal 的离线 XML/画面生成与转换脚本

这些文件是工程输入或可复用成果，不代表仍需从 Python 启动 TIA Portal。

## 工程操作

在 Codex 中使用 `$tia-portal-openness`。标准顺序是：

```text
Bootstrap
-> Connect
-> AttachToOpenProject 或 OpenProject
-> GetProjectTree
-> 导入/修改
-> CompileAndDiagnosePlc
-> SaveProject
```

完整工程优先使用 `ScaffoldProject`，并先执行 `dryRun=true`。下载前使用 `CheckDownloadReadiness`，再由 `DownloadToPlc` 执行下载。

不要重新引入 `pythonnet`、`clr` 或直接引用 `Siemens.Engineering`；缺少的工程能力应扩展 MCP 工作流。
