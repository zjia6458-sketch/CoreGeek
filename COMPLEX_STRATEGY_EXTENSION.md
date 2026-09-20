# FortressAgent V0.3.0 — Complex Strategy Extension Contract

V0.3.0 的核心目标不是继续扩充 `if/elif`，而是让“复杂策略”成为可注册组件。

整体原则：

```text
Policy Graph
    = 通用、安全、稳定的控制平面

Strategy Graph
    = 可替换、可组合、可跨回合的战略控制流

Candidate / Reward / Evaluator
    = 具体动作能力

TeamConstraint
    = 多角色联合动作的一致性与资源约束
```

因此新增策略不应该修改：

```text
PolicyGraphEngine
PolicyEngine
TeamPlanner main loop
FinalResponseValidator main loop
```

---

# 1. 为什么单个 StrategyProfile 不够

简单策略可以写成：

```text
EXPLORE
DEFENSE
GATHER
```

但真实复杂策略往往是：

```text
观察民间传说
    ↓
判断置信度
    ↓
收集三类任务物品
    ↓
确认是否接近西部目标区
    ↓
尝试祭坛
    ↓
根据 lastSummonTreasureResult 修正假设
```

或者：

```text
白天前半段经济
    ↓
距离夜晚 <= margin
    ↓
回防
    ↓
补药 / 修墙 / 升级
    ↓
夜晚武器分配
```

这些已经不是一个 `StrategyProfile` 可以自然表达的。

---

# 2. Strategy Graph

核心接口：

```python
class StrategyNode(ABC):
    node_id: str

    def run(
        self,
        ctx: PolicyContext,
        session: StrategySessionView,
    ) -> StrategyNodeResult:
        ...
```

节点不决定下一跳。

节点只返回：

```python
StrategyNodeResult(
    outcome="some_outcome",
    profile=...,
    state_updates={...},
)
```

下一跳由 Graph 注册表决定：

```text
(node_id, outcome)
        ↓
next_node
```

例如：

```python
graph = (
    StrategyGraphBuilder(
        "treasure_quest",
        "check_items",
    )
    .add_node(CheckItemsNode())
    .add_node(CollectKeysNode())
    .add_node(SearchWestNode())
    .add_node(SummonTreasureNode())

    .route(
        "check_items",
        "missing",
        "collect_keys",
    )
    .route(
        "check_items",
        "ready",
        "search_west",
    )
    .route(
        "collect_keys",
        "done",
        "search_west",
    )
    .route(
        "search_west",
        "altar_found",
        "summon",
    )
)
```

因此：

```text
新增节点
≠
修改 Graph Engine
```

而是：

```text
实现 Node
+
注册 Transition
```

---

# 3. 下一跳如何决定

这是 Strategy Graph 中最明确的约束：

```text
Node
 ↓
run(ctx, session)
 ↓
outcome
 ↓
transitions[(node_id, outcome)]
 ↓
next node
```

例如：

```python
class CheckItemsNode(StrategyNode):
    node_id = "check_items"

    def run(self, ctx, session):
        if has_three_keys(ctx):
            return StrategyNodeResult(
                outcome="ready"
            )

        return StrategyNodeResult(
            outcome="missing"
        )
```

Engine 完全不理解：

```text
key
treasure
night
market
```

Engine 只理解：

```text
outcome → next node
```

这是后续扩展复杂策略的核心。

---

# 4. Strategy Activator

“图内部怎么走”和“当前应该选哪张图”是两个问题。

通过：

```python
class StrategyActivator(ABC):
    def activate(
        self,
        ctx,
    ) -> StrategyActivation | None:
        ...
```

决定当前图。

例如：

```text
night
→ defense graph

day and turns_until_night <= margin
→ prepare graph

phaseTask != ""
→ active_task graph

otherwise
→ day_default graph
```

当前优先级：

```text
Night                priority 1000
Prepare              priority 900
Active Self Task     priority 850
Default Day          priority 100
```

新增一个新的复杂策略：

```text
Treasure Quest
```

只需要：

```text
TreasureQuestActivator
+
TreasureQuestGraph
```

然后注册。

不修改：

```text
GraphStrategySelector.select()
```

---

# 5. 跨回合 StrategySession

复杂策略不能每回合丢失进度。

新增：

```text
StrategySessionStore
```

它与 `PolicyState` 严格分离：

```text
PolicyState
    长期学习参数
    weights
    thresholds
    priors

StrategySession
    临时计划进度
    collected_keys
    target_region
    failed_attempts
    current hypothesis
```

Node 可以返回：

```python
StrategyNodeResult(
    outcome="continue",
    state_updates={
        "keys_found": 2,
        "last_search_round": 120,
    },
)
```

下一回合重新进入同一图时：

```python
session.data["keys_found"]
```

仍然存在。

因此可以实现真正的跨回合状态机，而不是把临时任务状态写入 `PolicyState`。

---

# 6. Strategy Graph 和 LLM 的关系

LLM 不成为 Graph Engine。

数据流：

```text
Folk Legend
 ↓
Lore Memory
 ↓
LLM prompt
 ↓
Pydantic StrategicAdvisory
 ↓
StrategicMemory
 ↓
StrategyNode
 ↓
outcome / objective
 ↓
Strategy Graph
```

所以 LLM 只能影响：

```text
图选择
节点 outcome
权重
长期 objective
```

不能绕过：

```text
LegalActionFilter
TeamConstraint
FinalResponseValidator
Deadline
```

---

# 7. LLM 调用调度

V0.3.0 新增：

```text
StrategicLLMCoordinator
```

规则：

```text
存在未分析的新 Lore
+
DAY
+
非自进化任务期间
+
正常 LLM daily budget 未耗尽
→ 生成结构化战略 prompt
```

实际 `prompt` 成功进入最终 Response 后：

```text
LLMBudgetTracker.record_call()
```

才扣额度。

夜间：

```text
不发送 Lore 分析 prompt
```

避免在高优先级 Defense 阶段浪费每日 3 次普通额度。

自进化任务期间则预留给独立 Task LLM Contract。

---

# 8. TeamConstraint

复杂策略的第二个问题是：

> 每个角色单独选择的最好动作，组合起来不一定合法。

例如：

```text
Worker1 wants Buy Medicine 10 gold
Worker2 wants Buy Medicine 10 gold

Current gold = 10
```

两个单动作都合法，但组合非法。

因此联合动作经过：

```text
TeamConstraintRegistry
```

当前注册：

```text
UniqueActorConstraint
WeaponControllerConstraint
GoldBudgetConstraint
InventoryConsumptionConstraint
UniqueBuildTargetConstraint
WeaponBuildLimitConstraint
```

每个 Constraint：

```python
class TeamConstraint(ABC):
    def apply(
        self,
        ctx,
        decisions,
    ) -> TeamConstraintResult:
        ...
```

新增共享资源限制：

```text
实现一个 TeamConstraint
+
register
```

不修改 `TeamConflictResolver`。

---

# 9. 当前已补业务插件

V0.3.0 已实现并注册：

```text
Attack
Gather
Move / Explore

Sell
Buy
Use

AcceptTask
SubmitAnswer provider hook

SummonTreasure provider hook

Build provider/catalog hook
```

其中：

## Sell

保守地要求角色位于：

```text
vendor
```

才生成 Sell Candidate。

## Buy

保守地要求角色位于：

```text
weaponShop
```

当前自动购买候选只开放：

```text
Medicine
WallFixer
```

并且必须有实际需求。

## Use

当前安全自动候选：

```text
Medicine
WallFixer
```

未明确效果/距离的：

```text
Bomb
DizzyWeapon
UpgradeVoucher
SummonOrder
```

暂不自动产生。

## AcceptTask

基于真实：

```text
PlayerTask.isValid
taskPosition
Pioneer position
```

生成。

## SubmitAnswer

通过：

```text
TaskAnswerProvider
```

注入。

默认：

```text
NoOpTaskAnswerProvider
```

不会凭空提交答案。

## SummonTreasure

通过：

```text
TreasurePlanProvider
```

注入。

默认不猜：

```text
targetPos
item combination
```

因为一次合法尝试就会消耗献祭物。

## Build

由于接口文档没有给：

```text
wall / weapon build resource recipe
```

默认：

```text
BuildCatalog = empty
```

不会自动建造。

拿到正式配方后只需：

```python
BuildCatalog((
    BuildRecipe(
        building_name="wall",
        required_items={
            "stone": ...,
        },
        strategic_value=...,
    ),
))
```

Candidate / Reward / TeamConstraint 不需要重写。

---

# 10. 新增复杂策略的标准流程

例如新增：

```text
TreasureQuestStrategy
```

推荐步骤：

```text
1. Feature
   treasure.xxx

2. Strategy Nodes
   CheckLore
   CheckItems
   CollectItems
   SearchRegion
   TrySummon

3. StrategyGraph
   注册 outcome transitions

4. Activator
   定义何时进入 TreasureQuestGraph

5. Candidate Plugin
   如需要新增动作空间

6. RewardModel
   定义动作原始价值

7. Evaluator
   Reward → Utility

8. TeamConstraint
   仅当产生新的跨角色共享冲突时增加

9. Unit / Contract / Scenario / Replay tests
```

不应该修改：

```text
PolicyGraphEngine
GraphStrategySelector
TeamPlanner main loop
FinalResponseValidator main loop
```

---

# 11. 当前完整控制结构

```text
HTTP Request
 ↓
GameState
 ↓
Memory
 ├── WorldMemory
 ├── StrategicMemory
 └── ExperienceMemory
 ↓
Feature
 ↓
Policy Graph
 ↓
StrategyActivatorRegistry
 ↓
StrategyGraph
 ↓
StrategySession
 ↓
StrategyProfile
 ↓
CandidateRegistry
 ↓
Legal / Rule
 ↓
Reward / Utility
 ↓
per-actor ranking
 ↓
TeamConstraintRegistry
 ↓
TeamDecision
 ↓
Wire Pydantic
 ↓
FinalResponseValidator
 ↓
HTTP Response
```

可以把它理解为：

```text
Policy Graph
    管“系统如何安全运行”

Strategy Graph
    管“当前战略如何演进”

Candidate / Evaluator
    管“具体动作怎么选择”

TeamConstraint
    管“多个动作能否共同执行”
```

四层职责明确分开。
