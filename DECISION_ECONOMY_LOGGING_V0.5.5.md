# V0.5.5：决策主链、夜前经济建设与三级日志

## 1. 为什么需要修改决策层

V0.5.4 中 RoleAction 已经有完整的 `Candidate -> Legal -> Rule -> Rank -> Decision -> Experience -> Outcome`，但 `prompt` 与 `executeCmd` 仍只是 `TeamDecision` 上的字符串。它们确实能通过协议生效，却缺少独立 decision id、来源 node 和结果归因，导致任务沙盒行为难以回放，也可能把“计划过但最终未发送”的命令误当成 TaskSkill。

V0.5.5 新增：

```text
TurnDecision
├─ Role Decision[]
│  └─ Action -> Experience -> Outcome
└─ AuxiliaryDecision[]
   ├─ PromptDecision
   │  └─ llmResp -> AuxiliaryOutcome
   └─ ExecuteCommandDecision
      └─ lastCmdResult -> AuxiliaryOutcome
```

`executeCmd` 仍然不是 RoleAction，因为一个回合可以同时 `Worker build + Worker collect + executeCmd`。但它现在是正式领域决策，不再是旁路字符串。

### 发送确认

TaskSession 只负责“规划”命令。只有命令通过 FinalResponseValidator 且没有被 suppress 后，Runtime 才调用 `record_dispatched()` 写入任务命令轨迹。如果 HTTP 层确认响应没有送达，则调用 `retract_dispatched()` 撤销该轨迹。

因此 TaskSkill 只学习实际准备发送且没有被最终校验丢弃的命令。

## 2. 采矿效率：从单块往返改为批量运输

旧问题：三塔完成后，Worker 背包里只要出现 1 个 stone，`WallBuildApproach` 就可能开始返场。矿点到基地距离较远时，大部分回合消耗在来回走路。

新规则：

- Day1 夜前最低墙体目标：8；
- Day2：12；Day3：16；Day4+：20；
- 正常情况下每名 Worker 先收集最多 4 个 stone 再返场；
- 距离入夜 <=25 回合时，批量目标降为 1，已有 stone 立即返场；
- 三塔完成且当日墙体目标未达到，只要地图存在 stone，两个 Worker 都优先 stone；
- 达到 stone 批量目标后，不再生成 ResourceApproach，确保返场候选接管；
- prepare 阶段不再远距离追矿，但若 Worker 已经站在 stone 邻域，可原地再 `collect` 一次，然后返场。

这样把经济链固定为：

```text
三座 Rocket 完成
  -> 两 Worker stone 模式
  -> 批量 collect
  -> 返回 wall ring
  -> 两 Worker 可并行 build wall
  -> 若仍有时间再进行下一轮
  -> prepare 时停止远距离采矿
```

## 3. 为什么不是单纯提高 reward

这次关键规则直接进入 Candidate 生成条件。如果 Worker 已经达到批量 stone 目标，ResourceApproach 根本不会生成；如果夜前墙目标未达到且 stone 存在，非 stone 资源候选会被过滤。因此不会因为 exploration/copper 的 utility 偶然较高再次打断施工链。

Reward 仍用于在合法候选之间排序，但不承担关键阶段控制。

## 4. 日志三级化

默认 `LOG_MODE="medium"`。

- LOW：最小 Round/Action/ExecCmd block；
- MEDIUM：当前完整的人类可读 block；
- HIGH：MEDIUM + 全量结构化日志。

LOW/MEDIUM 的 root logger 使用 `%(message)s`，因此不会出现 `timestamp | INFO |` 前缀；HIGH 保留时间戳用于精确排障。
