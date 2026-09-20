# FortressAgent V0.3.4 — 单日志运行时闭环示例

本文说明比赛真实入口 `python main3.py <port>` 下，一次服务器 Response 如何经过协议解析、世界记忆、复杂策略、动作候选、联合决策、最终校验并返回；以及下一回合反馈如何形成 Outcome、Experience 和学习样本。

V0.3.4 的一个重要运行约束是：**生产环境只有一个物理日志出口**。所有可观测信息都通过 `main3.py` 配置的 root stdout logger 输出，不创建 `trace.jsonl / io.jsonl / experience.jsonl / world_events.jsonl`。

---

## 1. 生产入口

判题系统执行：

```bash
python main3.py 8080
```

调用链：

```text
main3.py
  ↓ logging.basicConfig(stream=sys.stdout, ...)
  ↓ root logger
  ↓ from agent.server import serve
agent.server.serve(8080)
  ↓ build_runtime(logger=root_logger)
  ↓ run_http_server(host="0.0.0.0", port=8080)
  ↓ HttpTurnService.handle(...)
  ↓ FortressAgentRuntime.handle_turn(...)
```

`main3.py` 是唯一允许调用 `logging.basicConfig()` 的模块。

框架内部只调用：

```python
logging.getLogger()
```

因此所有记录最终都进入判题系统唯一可下载的 stdout 日志。

---

# 2. 单日志中的逻辑通道

物理上只有一个日志，逻辑上通过 `channel` 区分：

```text
system       启动、运行时配置
io           服务器 Request / Response / parse error
world_event  地图事实事件
trace        Runtime / PolicyGraph / Strategy / TeamDecision / Validator
experience   ExperienceRecord / OutcomeRecord / CreditLink
```

例如：

```text
2026-... | INFO | {"channel":"io","record_type":"request",...}
2026-... | INFO | {"channel":"world_event","event_type":"ResourceDiscovered",...}
2026-... | INFO | {"channel":"trace","record_type":"trace","event":{"kind":"strategy_selected",...}}
2026-... | INFO | {"channel":"experience","record_type":"experience",...}
```

同一回合统一使用：

```text
correlation_id = r<round>:attempt:<request_sequence>
```

例如：

```text
r10:attempt:1
```

因此从唯一日志中执行：

```bash
grep '"correlation_id":"r10:attempt:1"' game.log
```

即可获得该回合完整调用轨迹。

---

# 3. 示例场景

假设 Round 10 服务器输入的关键状态为：

```text
Round = 10
Phase = day

Worker 10010 = (5,4)
Pioneer 10011 = (10,12)

Stone = (5,5)
Score = 0

folkLegends:
西部有一石门，门需三钥
```

这里特别注意 V0.3.3 后的硬约束：

```text
Stone (5,5) 是不可通行交互格
Worker 必须位于相邻格 (5,4) 才能 collect(5,5)
```

不能执行：

```text
move(5,5)
```

---

# 4. Step A — HTTP 接收 Request

HTTP 层：

```text
HttpTurnService.handle(body)
```

进入：

```python
await FortressAgentRuntime.handle_turn(body)
```

Runtime 为这次调用建立：

```text
request sequence = 1
correlation_id = r10:attempt:1
```

单日志首先出现：

```json
{
  "channel": "io",
  "record_type": "request",
  "correlation_id": "r10:attempt:1",
  "round_id": 10,
  "payload": { "...": "official request" }
}
```

---

# 5. Step B — 协议解析

调用：

```text
GameProtocolCodec.parse_state(raw_response)
```

真实接口走：

```text
ServerGameResponseDTO
    ↓ Pydantic
GameStateBuilder.build_server()
    ↓
GameState
```

这一阶段负责把服务器字段：

```text
roundNo
mapInfo
teamOur
teamEnemy
robot
worldNews
lastRoundRoleActionResults
llmResp
...
```

规范化为内部稳定模型。

例如：

```text
roundNo=10
→ day=1
→ phase=day
```

角色：

```text
teamOur.roles
→ CharacterState / BuildingState
```

矿点：

```text
mapInfo.zones[stone]
→ ResourceNodeState
```

Runtime 同时输出：

```json
{
  "channel":"trace",
  "record_type":"trace",
  "event":{
    "kind":"state_parsed",
    "round_id":10,
    "correlation_id":"r10:attempt:1",
    "data":{
      "characters":2,
      "resources":1
    }
  }
}
```

---

# 6. Step C — Observation → DomainEvent → WorldMemory

调用：

```text
WorldMemoryEngine.observe(state, correlation_id)
    ↓
ObservationInterpreter.interpret(...)
    ↓
DomainEvent[]
    ↓
MapMemoryProjector / ResourceMemoryProjector
    ↓
WorldMemory
```

可能产生：

```text
CellObserved
CellVisited
ResourceDiscovered
```

例如：

```json
{
  "channel":"world_event",
  "event_type":"ResourceDiscovered",
  "payload":{
    "round_id":10,
    "correlation_id":"r10:attempt:1",
    "resource_id":"zone:stone:5:5",
    "resource_type":"stone",
    "x":5,
    "y":5
  }
}
```

此时 WorldMemory 中：

```text
zone:stone:5:5
status = AVAILABLE
```

同时 `TraversabilityMap` 会把 `(5,5)` 标记为：

```text
resource_cell
→ not walkable
```

---

# 7. Step D — StrategicMemory 与 LLM

`worldNews.folkLegends` 首先进入：

```text
StrategicMemory.observe_lore(...)
```

如果是尚未分析的新 Lore：

```text
StrategicLLMCoordinator.plan(...)
```

会检查：

```text
是否白天
是否不是自进化任务期
是否还有每日正常 LLM 额度
该 Lore 是否尚未请求分析
```

满足条件后生成：

```text
StrategicPromptBuilder.build(state)
```

这个 Prompt 只要求 LLM 返回 `StrategicAdvisory` JSON，不允许直接生成动作。

---

# 8. Step E — PolicyContext

调用：

```text
PolicyContextFactory.build(...)
```

得到统一决策上下文：

```text
PolicyContext
├── GameState
├── WorldMemoryView
├── StrategicMemoryView
├── PolicyState
├── Deadline
├── Features
└── correlation_id
```

之后所有策略与动作插件都只消费 `PolicyContext`，不直接依赖服务器原始 JSON。

---

# 9. Step F — Policy Graph

调用：

```text
PolicyGraphEngine.run(ctx)
```

控制流大致为：

```text
runtime_gate
→ strategy
→ candidates
→ legal_filter
→ rules
→ rank
→ validate
→ finalize
```

每个节点只返回：

```text
outcome
```

Graph 根据：

```text
(node_id, outcome) → next_node
```

决定下一跳。

这些节点执行信息全部进入 `channel=trace`。

---

# 10. Step G — Strategy Graph

策略选择由：

```text
StrategyActivatorRegistry
    ↓
GraphStrategySelector
    ↓
StrategyGraphEngine
```

完成。

Round 10 的 Worker 位于可采矿点邻格，因此经济机会存在，可能形成：

```text
day_default
    ↓
long_horizon_decision
    ↓ outcome=economy
 economy_profile
    ↓
END
```

最终：

```text
strategy_id = economy
```

日志：

```json
{
  "channel":"trace",
  "record_type":"trace",
  "event":{
    "kind":"strategy_selected",
    "correlation_id":"r10:attempt:1",
    "data":{
      "strategy_id":"economy",
      "metadata":{
        "strategy_graph":"day_default",
        "strategy_visited_nodes":[
          "long_horizon_decision",
          "economy_profile"
        ]
      }
    }
  }
}
```

---

# 11. Step H — Candidate Registry

`CandidateService` 根据 Strategy 的 tags 调用已注册插件，例如：

```text
GatherCandidateGenerator
ResourceApproachCandidateGenerator
MoveCandidateGenerator
ExplorationCandidateGenerator
SellCandidateGenerator
...
```

对于 Worker `(5,4)` 和 Stone `(5,5)`：

```text
GatherCandidateGenerator
→ GatherAction(resource_id="zone:stone:5:5")
```

同时 P0 Traversability 保证：

```text
MoveCandidateGenerator
不会生成 move(5,5)
```

---

# 12. Step I — LegalActionFilter

所有 Candidate 再经过：

```text
BasicLegalActionFilter.filter(...)
```

对于 Gather：

```text
actor.role == worker
phase == day
resource.status == AVAILABLE
Manhattan(worker, resource) == 1
```

才合法。

对于 Move：

```text
TraversabilityMap.is_walkable(target) == True
```

资源格、建筑 footprint 等硬障碍直接被淘汰。

---

# 13. Step J — Reward / Utility / Rank

候选动作调用对应：

```text
ExpectedRewardModel
    ↓
RewardBreakdown
    ↓
UtilityComposer
    ↓
UtilityBreakdown
```

例如：

```text
GatherAction
→ GatherRewardModel
→ economy / information / action_cost / risk
→ GatherEvaluator
```

`RewardAwareRanker` 为每个角色选择 Utility 最优动作。

---

# 14. Step K — TeamPlanner 与 TeamConstraint

真实协议允许多个角色同回合各提交一个动作，因此：

```text
TeamPlanner.plan(...)
```

会先按 actor 分组选最优动作，再执行：

```text
TeamConstraintRegistry
```

包括：

```text
UniqueActorConstraint
WeaponControllerConstraint
GoldBudgetConstraint
InventoryConsumptionConstraint
UniqueBuildTargetConstraint
WeaponBuildLimitConstraint
```

假设本轮得到：

```text
10010 → GatherAction
10011 → MoveAction
```

日志：

```json
{
  "channel":"trace",
  "record_type":"trace",
  "event":{
    "kind":"team_decision_planned",
    "correlation_id":"r10:attempt:1",
    "data":{
      "decision_count":2,
      "actions":[
        {"actor_id":"10010","action_type":"gather"},
        {"actor_id":"10011","action_type":"move"}
      ]
    }
  }
}
```

---

# 15. Step L — DomainAction → Wire Command

调用：

```text
DecisionResponseEncoder.encode_team_detailed(...)
    ↓
DomainActionMapper
```

内部 Gather：

```text
GatherAction(resource_id)
    ↓ WorldMemory
resource position = (5,5)
    ↓
collect.targetPos=(5,5)
```

得到：

```json
{
  "roleCommandMap":{
    "10010":{
      "action":"collect",
      "targetPos":[{"x":5,"y":5}]
    },
    "10011":{
      "action":"move",
      "targetPos":[{"x":10,"y":11}]
    }
  },
  "prompt":"...structured LLM prompt...",
  "executeCmd":""
}
```

---

# 16. Step M — FinalResponseValidator

发送服务器之前最后执行：

```text
FinalResponseValidator.validate(...)
```

这里不再关心 Utility，而只检查硬合法性。

例如 Collect 必须满足：

```text
Worker
Day
Resource exists
Distance == 1
```

Move 必须满足：

```text
一步移动
地图内
目标格 walkable
目标格不是 stone / iron / copper
```

因此即使某个未来插件错误生成：

```text
move(5,5)
```

Final Validator 仍会以：

```text
move_target_blocked
```

拒绝，避免非法指令累计异常。

---

# 17. Step N — ExperienceRecord

只有**最终真正被接受、准备发送服务器的动作**才建立 Experience。

调用：

```text
ExperienceBuilder.build_decision(...)
    ↓
JournaledExperienceStore.append(...)
```

这里 Journal 的物理目标不是文件，而是：

```text
LoggerJsonWriter(channel="experience")
→ root logger
```

日志例如：

```json
{
  "channel":"experience",
  "record_type":"experience",
  "experience":{
    "experience_id":"exp:r10:attempt:1:...",
    "decision_id":"r10:attempt:1:...",
    "round_id":10,
    "strategy_id":"economy",
    "action":{
      "actor_id":10010,
      "action_type":"gather"
    }
  }
}
```

---

# 18. Step O — HTTP Response

最终 response 由：

```text
IoJournal.record_response(...)
```

进入同一个 root logger：

```json
{
  "channel":"io",
  "record_type":"response",
  "correlation_id":"r10:attempt:1",
  "round_id":10,
  "payload":{
    "roleCommandMap":{ "...":"..." },
    "prompt":"...",
    "executeCmd":""
  }
}
```

然后 HTTP 200 返回判题器。

至此第一回合决策完成。

---

# 19. Round 11 — 服务器反馈

下一回合假设服务器返回：

```text
lastRoundRoleActionResults:
10010 = true
10011 = true

Stone(5,5) 从 mapInfo.zones 消失
Worker backpack 增加 stone
Score: 0 → 2

llmResp:
结构化 StrategicAdvisory
recommended_mode = explore
target_region = west
```

新的调用拥有：

```text
correlation_id = r11:attempt:2
```

---

# 20. ResourceDepleted

`ObservationInterpreter` 对完整 `mapInfo.zones` 发现：

```text
Round10: stone(5,5) exists
Round11: stone(5,5) missing
```

产生：

```text
ResourceDepleted
```

并更新：

```text
WorldMemory
zone:stone:5:5
AVAILABLE → DEPLETED
```

单日志：

```json
{
  "channel":"world_event",
  "event_type":"ResourceDepleted",
  "payload":{
    "correlation_id":"r11:attempt:2",
    "resource_id":"zone:stone:5:5"
  }
}
```

之后 Candidate Generator 不会再次尝试采这个矿。

---

# 21. RealizedReward

调用：

```text
RealizedRewardCalculator.calculate(
    previous_state,
    current_state,
    memory_delta,
)
```

例如：

```text
score delta = +2
inventory +1 stone
stone price = 1
```

得到：

```text
RealizedReward.total = 3.0
```

---

# 22. Team Credit Assignment

Round 10 实际发送两个动作：

```text
10010 gather
10011 move
```

服务器反馈：

```text
both legal
```

`TeamCreditAssigner` 当前第一版在合法动作之间平均分配：

```text
3.0 / 2 = 1.5
```

因此：

```text
Gather outcome reward = 1.5
Move outcome reward   = 1.5
```

如果：

```text
lastRoundRoleActionResults[10011] = false
```

则该动作：

```text
action_legal = false
reward credit = 0
```

Learner 会跳过非法动作样本，避免把“命令非法”错误学习成“策略收益低”。

---

# 23. OutcomeRecord

调用：

```text
ExperienceBuilder.build_outcome(...)
    ↓
ExperienceStore.attach_outcome(...)
```

统一日志：

```json
{
  "channel":"experience",
  "record_type":"outcome",
  "outcome":{
    "outcome_id":"outcome:...:11",
    "end_round":11,
    "action_legal":true,
    "reward":{"total":1.5}
  },
  "credits":[...]
}
```

然后：

```text
OnlineLearner.observe(
    experience,
    outcome
)
```

完整学习闭环形成。

---

# 24. LLM Advisory 进入下一轮 Strategy

Round 11 的 `llmResp` 经过：

```text
StrategicLLMResponseParser
    ↓ Pydantic
StrategicAdvisory
    ↓
StrategicMemory
```

假设：

```text
recommended_mode = explore
confidence = 0.7
mode_strength = 0.8
```

有效强度：

```text
0.7 × 0.8 = 0.56
```

超过策略阈值后：

```text
StrategyGraph
long_horizon_decision
    ↓ outcome=llm_explore
llm_explore_profile
```

LLM 只改变长期策略偏好。

真正 Move 仍必须经过：

```text
Candidate
→ Traversability
→ Legal
→ Reward
→ TeamConstraint
→ FinalResponseValidator
```

所以：

```text
LLM influences strategy
≠
LLM directly controls action
```

---

# 25. 从唯一日志重建完整闭环

假设下载得到：

```text
game.log
```

查看 Round 10：

```bash
grep '"correlation_id":"r10:attempt:1"' game.log
```

查看所有 Experience：

```bash
grep '"channel":"experience"' game.log
```

查看世界变化：

```bash
grep '"channel":"world_event"' game.log
```

查看最终校验：

```bash
grep 'final_response_validated' game.log
```

查看非法动作反馈：

```bash
grep '"action_legal":false' game.log
```

因此只需要一个日志下载出口，就能恢复：

```text
Server Request
→ Parsed GameState
→ DomainEvent
→ WorldMemory
→ StrategyGraph
→ Candidate
→ Reward/Utility
→ TeamDecision
→ Final Validation
→ Server Response
→ Experience
→ Next Server Feedback
→ RealizedReward
→ Outcome
→ Learner
```

这就是 V0.3.4 的生产运行闭环。


## COMMAND_ERROR feedback loop (V0.3.7)

When a server response reports an impassable MOVE, Runtime parses it before the next policy decision. The lesson is stored in `RuntimeFeedbackMemory`, attached to the prior `OutcomeRecord`, emitted as `command_error_learned`, and injected into both `TraversabilityMap` and the next safety-revision strategic prompt. Thus a failed move cannot be blindly replayed on the following turn.
