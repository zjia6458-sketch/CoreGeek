# FortressAgent V0.3.6 — Strategy Loop & Log Mode Repair

## 1. 修复目标

本版本针对真实日志暴露的四个策略问题与日志膨胀问题：

```text
Pioneer 两格往返
Worker 只采不卖
Prepare 不回基地
Night 无武器时仍无意义 move
日志重复过多
lastCmdResult 未进入独立 Agent Memory
```

## 2. Pioneer 不再是纯移动角色

`economy` 的 tags 从：

```text
gather / sell / buy / use / move
```

扩展为：

```text
gather / sell / buy / use / move / explore / task / treasure
```

新增 `TaskApproachCandidateGenerator`。

Pioneer 若存在有效任务点但尚未到达，会通过 A* 生成朝任务点前进的
`GoalApproachAction(goal_kind="task")`。Task reward 会随剩余距离折算，避免普通局部 move 抢走任务导航。

## 3. 防止两格振荡

普通 `MoveRewardModel` 不再因为进入“已探索格”获得正 position reward。

新增：

```text
revisit_penalty = min(0.75, 0.08 * visit_count)
```

因此反复访问 `(8,20)↔(8,21)` 会越来越差。

同时 Strategy 可以声明：

```text
minimum_action_utility
```

`defense` 默认阈值为 `0.5`。没有攻击/使用等有效动作时，`TeamPlanner` 可以直接不为角色发命令，而不是强迫 move。

## 4. Worker 经济闭环

新增长期导航候选：

```text
ResourceApproach  → 采集
VendorApproach    → 卖矿
WeaponShopApproach → 需要时购买
BaseReturn        → prepare 回基地
```

同时把 `GatherRewardModel.default_gather_units` 从 10 修正为 1，避免系统严重高估单回合 collect，导致永远采集、不愿变现。

当 Worker 已携带较高价值矿物时，`VendorApproach` 的经济价值会超过继续采集，从而启动：

```text
collect → travel vendor → sell
```

## 5. Prepare 回基地

`prepare` tags 增加：

```text
build / sell
```

`BaseReturnCandidateGenerator` 会寻找己方 2×2 station footprint 周围的可通行 ring，使用 A* 将 Worker 拉回基地附近。

到达 ring 后，如果存在已验证 `BuildRecipe`，`BuildCandidateGenerator` 可以生成基地附近建筑。

## 6. BuildCatalog：不猜协议

接口文档没有给 wall/gatling/railgun/rocket 的准确物料数量。

因为非法 build 会计入异常，默认代码**不会猜配方**。

`main3.py` 顶部新增唯一配置：

```python
BUILD_RECIPES = {
    # "wall": {
    #     "required_items": {"stone": VERIFIED_COUNT},
    #     "strategic_value": 5.0,
    # },
}
```

`BuildCatalog.from_mapping()` 只接受这里的已验证配方。

一旦配置，链路为：

```text
prepare
→ BaseReturn
→ worker reaches base ring
→ BuildCandidateGenerator
→ BuildRewardModel
→ TeamConstraint
→ FinalResponseValidator
→ build command
```

已有集成测试验证配置 `wall: stone×1` 后会实际生成 build；这只是测试 fixture，不代表比赛真实配方。

## 7. Night attack / no-op

已有 `AttackCandidateGenerator(tags={defense})` 保留。

现在：

```text
存在 weapon + 合法 target + utility >= threshold
→ attack

没有 weapon / target
→ roleCommandMap 可为空
```

不再用低价值 move 假装“防守”。

## 8. RuntimeFeedbackMemory

新增：

```text
RuntimeFeedbackMemory
RuntimeFeedbackMemoryView
RuntimeFeedbackRecord
```

每回合无条件保存：

```text
lastRoundRoleActionResults
lastSummonTreasureResult
lastCmdResult
server errors
```

这是 Agent Memory，与 logger 完全独立。

`PolicyContext.feedback_memory` 允许未来 Strategy/Learner 直接读取命令执行历史。

## 9. Logger FULL / COMPACT

`main3.py`：

```python
LOG_MODE = "compact"   # or "full"
```

### COMPACT

保留：

```text
strategy_selected
team_decision_planned + utility + matched_rules + action_repr
final_response_validated
server_feedback_observed
lastCmdResult
LLM advisory accepted/rejected
important resource changes
Experience summary
Outcome summary
final wire response
turn_completed
```

省略：

```text
raw request body
每个 policy node transition
CellObserved / CellVisited
重复的 control-plane中间态
完整 feature vector
```

### FULL

保留所有原始 structured records，用于深度调试。

## 10. 关键不变量

```text
LogMode 只改变人类日志投影
Memory / Experience / Policy State 不读取 LogMode
```

集成测试会用完全相同的两回合输入分别跑 FULL 与 COMPACT，并断言：

```text
WorldMemory 相同
RuntimeFeedbackMemory 相同
Experience 数量相同
COMPACT 日志条数 < FULL
```
