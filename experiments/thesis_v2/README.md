# 硕士论文试验 V2 记录包

本目录把 `config/thesis_experiment_v2.yaml` 的 E0-E9 预注册方案转成可直接填写的记录模板。所有模板保留 `data_status` 字段，允许值只有：`literature_original`、`literature_scaled`、`experimental_design`、`measured`。

执行顺序固定为 E0→E1→E2→E3→E4→E5→E6→E7→E8→E9。E4 未通过时，PLC 的 `Decoupler_Enable` 必须永久为 FALSE。

第65天采用双标签：生物学观测阶段为 MID，灌溉配方阶段为 LATE。旧四套 EC/pH SAC 模型已归档，不得用于 V2 推理。
