# 日志模式（V0.5.6）

生产日志仍只有 `main3.py` 配置 root stdout logger。Memory/Experience/Policy 永远不能从 logger 反向读取状态。

## LOW

只输出 `=====START=====` 与 `=====END=======` 之间的回合核心摘要：Round/Day/Phase、Gold/Score、最终 Role Action、必要的 ExecCmd/TaskStage，以及本回合真实发生的 `LearningUpdate`。

不输出 Nodes、单位明细、Utility 公式、JSON trace/io/experience。

## MEDIUM（默认）

在 LOW 基础上增加：

- Strategy 与 PolicyGraph node 链；
- 己方角色/建筑状态；
- 动作 goal 与最终 utility；
- `UtilityFormula`：Reward 分量 × 有效权重；
- ResourceApproach 的 `ResourceFormula`；
- LearningUpdate 的 proposer/confidence/next update round；
- DeadlineRemaining。

仍不输出结构化 JSON trace/io/experience，方便直接人工阅读比赛日志。

## HIGH

输出 MEDIUM 人类摘要 + 全量结构化：trace、io、experience、world_event、auxiliary decision/outcome、runtime policy update、HTTP/system。用于框架开发和精确回放。

兼容旧名字：`compact -> medium`，`full -> high`。
