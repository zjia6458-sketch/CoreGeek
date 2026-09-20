# FortressAgent V0.2.6 — Complete Runtime / Learning Data Flow

V0.2.6 在 V0.2.5 的主决策链上补齐了学习与安全演进闭环。

---

# 1. 在线决策数据流

```text
Raw JSON
  ↓
Protocol / Pydantic
  ↓
GameState
  ↓
ObservationInterpreter
  ↓
DomainEvent
  ├──────────────→ EventStore
  ↓
MemoryProjector
  ↓
WorldMemory
  ↓
FeatureRegistry
  ↓
PolicyContext
  ↓
Policy Graph
  ↓
StrategyProfile
  ↓
CandidateGenerator
  ↓
LegalFilter
  ↓
RuleEngine
  ↓
ExpectedRewardModel
  ↓
UtilityComposer
  ↓
Evaluator / Ranker
  ↓
Validator
  ↓
Decision
  ↓
ExperienceRecord
  ↓
DomainActionMapper
  ↓
Strict Outbound JSON
```

---

# 2. 下一回合反馈流

```text
Previous GameState
      +
Current GameState
      +
MemoryDelta
      ↓
RealizedReward
      ↓
OutcomeRecord
      ↓
CreditLink
      ↓
ExperienceStore
      ↓
OnlineLearner.observe()
```

第一版采用：

```text
decision(t)
    ↓
reward observed at t+1
```

的直接一回合 Credit Assignment。

对于：

```text
Build
Task
Market
```

这种延迟效果动作，后续只需要增加额外 `CreditLink`，不改变 ExperienceRecord。

---

# 3. ExperienceStore

当前接口已经支持：

```text
append decision
attach outcome
recent
all
outcome_for
aggregate
```

Aggregate 使用：

```text
ContextKey(
    phase,
    strategy,
    action_type,
)
```

维护 `RunningStats`。

下一步可将 `CompositeExperienceStore` 内部替换为：

```text
HotBufferStore
+
AggregateStore
+
SQLite / JSONL ColdStore
```

Learner 不需要修改。

---

# 4. Learner 不直接改策略

严格数据流：

```text
Experience
  ↓
Learner.observe
  ↓
Learner.propose
  ↓
PolicyPatch
  ↓
PolicyStateRepository.create_candidate
```

而不是：

```text
Learner
→ mutate Current PolicyState
```

当前第一批 Learner：

```text
PrepareMarginLearner
UtilityWeightLearner(economy)
```

所有 Patch：

```text
bounded
small-step
versioned
reversible
```

---

# 5. Current / Candidate Policy

```text
PolicyStateRepository
│
├── Current / Champion
│
└── Candidate / Challenger
```

Candidate 创建后并不会自动成为 Current。

必须进入：

```text
Shadow
→ Report
→ PromotionGate
```

---

# 6. Shadow 数据流

```text
Same PolicyContext
     │
     ├── Champion PolicyState
     │       ↓
     │    Decision A
     │
     └── Candidate PolicyState
             ↓
          Decision B

A + B
  ↓
CounterfactualEstimatorRegistry
  ↓
ShadowEvaluationRecord
  ↓
ShadowReport
  ↓
PromotionGate
```

---

# 7. Counterfactual Estimator

当前实现：

```text
ExactSameActionEstimator
        ↓ priority
DirectUtilityEstimator
```

其中：

- Same Action：高置信度；
- Different Action：当前只使用低置信度 Direct Utility fallback。

后续扩展顺序：

```text
ShortHorizonSimulator
HistoricalMatchEstimator
DoublyRobustEstimator
IPS / SNIPS
```

Registry 与 ShadowEvaluator 不需要改变。

---

# 8. Promotion 是 Hard Gate

Candidate 必须同时满足：

```text
invalid_rate == 0
timeout_rate == 0
enough samples
enough context coverage
risk delta <= threshold
P99 latency <= budget
LCB(delta utility) > 0
```

不能：

```text
高收益
抵消
非法动作 / timeout
```

---

# 9. Rollback

Promotion 之后仍继续收集真实 Experience。

`RollbackPolicy` 检查：

```text
severe negative outcome
recent mean reward degradation
```

安全事件未来可直接接：

```text
immediate rollback
```

---

# 10. Replay

新增：

```text
ReplayCase
ReplayEngine
ReplayResult
```

用于：

```text
old state
+
specific policy version
→ rerun decision
```

这会成为：

```text
Regression Test
Shadow Debug
Policy Diff
```

的公共基础。

---

# 11. 协议依赖能力

Attack / Build 目前新增：

```text
AttackPluginContract
BuildPluginContract
```

但不提供伪实现。

原因是它们依赖正式服务器对于：

```text
weapon operator
attack actor_id
direction / target semantics
build resource cost
build occupancy
```

的真实协议。

在 Wire Schema 未确认前：

```text
补接口
不猜行为
```

比实现一个可能导致比赛非法指令的插件更安全。

---

# 12. 当前完整双闭环

## World Model Loop

```text
Observation
→ Event
→ WorldMemory
→ Features
→ Decision
```

## Policy Learning Loop

```text
Decision
→ Experience
→ Outcome
→ Learner
→ PolicyPatch
→ Candidate
→ Shadow
→ Promotion / Rollback
```

因此 FortressAgent 当前架构已经从：

```text
stateless rule agent
```

演进为：

```text
stateful
experience-driven
versioned
shadow-verified
policy system
```

---

# 13. 仍待真实协议确认后完成

框架层剩余的主要业务插件：

```text
AttackCandidate / Reward / Evaluator
BuildCandidate / Reward / Evaluator
TaskCandidate / Reward / Evaluator
TradeCandidate / Reward / Evaluator
TreasureCandidate / Reward / Evaluator
```

这些都已经有稳定接入路径：

```text
Action
→ CandidateGenerator
→ RewardModel
→ Evaluator
→ Registry
```

不需要修改 PolicyGraphEngine。


## Competition process entry

```text
python main3.py <port>
    ↓
main3.main()
    ↓
agent.server.serve(port)
    ↓
build_runtime(root_logger)
    ↓
run_http_server(host=0.0.0.0, port=<port>)
    ↓
HTTP POST → FortressAgentRuntime.handle_turn(...)
```


## V0.3.4 single logging outlet

Production no longer creates independent runtime JSONL journals. `main3.py` configures the one root stdout logger and `build_runtime()` routes `io`, `world_event`, `trace`, and `experience` structured records into that logger. Filter the single downloaded log by `channel` and `correlation_id`.
