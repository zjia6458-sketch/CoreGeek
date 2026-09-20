# FortressAgent V0.2.9 — Official Interface Alignment & Team Runtime

## 1. 官方接口修正

V0.2.9 根据完整接口文档修正：

```text
Role.cooldown
PlayerTask.timeoutRounds
RobotRole.targetTeam
errors=current-round errors
station footprint=2×2, pos=top-left
sell/buy num default=1
targetPos upper bounds depend on mapInfo.width/height
```

`errors` 不再错误映射成累计异常次数：

```text
GameState.round_error_count
GameState.server_errors
```

早期 `anomaly_count` 仅保留兼容，不由官方 `errors` 推导。

---

## 2. Wire Schema vs State Validator

当前输出验证分两层：

```text
Pydantic Wire Schema
    ↓
JSON shape / non-empty required field
    ↓
FinalResponseValidator
    ↓
current map / role / phase / inventory / cooldown / task state
```

这样 `mapInfo.width/height` 不再被硬编码进 Pydantic。

---

## 3. FinalResponseValidator 已验证

### 通用

- roleCommandMap key 必须属于己方单位；
- targetPos 必须在当前 map bounds；
- executeCmd 仅任务期间允许；
- LLM normal quota exhausted 时 prompt 被抑制。

### attack

- 仅 night；
- key 必须是 gatling / railgun / rocket；
- controllerId 必须是己方 worker/pioneer；
- 一个 controller 同回合最多控制一座武器；
- controller 保守地视为本回合已被占用，不能再执行自己的直接命令；
- railgun targetPos 数量固定 1；
- gatling / rocket targetPos 数量 = weapon level；
- rocket cooldown > 0 时拒绝。

### collect/build/remove/task/item

按官方接口和已经确认的比赛规则进行状态校验，避免字段正确但业务非法。

---

## 4. LLM 每日额度

新增：

```text
LLMBudgetTracker
```

正常状态：

```text
3 calls / game day
```

round 1~130 属于 day1，131~260 属于 day2。

进入自进化任务（`phaseTask` 非空）：

```text
LLM call is exempt
not counted in daily normal budget
```

收到：

```text
errorCode = 5
```

当前日 normal budget 立即视为不可继续调用。

---

## 5. lastRoundRoleActionResults 进入 Outcome

服务器反馈：

```text
role id -> true / false
```

现在进入：

```text
OutcomeRecord.action_legal
```

Learner 遇到：

```text
action_legal == false
```

不会把它当作普通 reward prediction error 来调整 Utility 权重。

否则会发生错误学习：

```text
illegal command
→ reward low
→ wrongly decrease useful strategy weight
```

现在非法性和价值学习被分离。

同时 Outcome 保存：

```text
server_error_codes
lastSummonTreasureResult
lastCmdResult
```

---

# 6. TeamDecision

真实协议允许：

```text
多个角色同回合各 1 条指令
```

因此新增：

```text
TeamDecision
TeamPlanner
TeamConflictResolver
```

数据流从：

```text
argmax_a U(s,a)
```

升级为：

```text
candidate actions
    ↓
group by actor
    ↓
best action per actor
    ↓
cross-role conflict resolution
    ↓
TeamDecision
    ↓
roleCommandMap
```

---

## 7. ConflictResolver

当前处理：

- 同一个 actor 重复动作：保留 utility 更高者；
- 同一 controller 控制多座武器：保留 utility 更高的 attack；
- controller 同时拥有自己直接动作：与 attack 比较 utility，只保留一项；
- tie-break 保持 deterministic。

以后可继续增加：

```text
same build cell
same scarce item
same gold allocation
same task ownership
same target occupancy
```

---

## 8. 第一版 Attack Plugin 已启用

现在真实协议已确认，因此实现：

```text
AttackAction
AttackCandidateGenerator
AttackRewardModel
AttackEvaluator
```

生成规则：

```text
night only
weapon = gatling / railgun / rocket
rocket cooldown == 0
controller = own mobile character
target count obeys level/interface rule
```

由于官方文档提供 `attackRange` 但未定义具体几何距离公式，候选生成暂时使用 **Manhattan distance** 作为保守过滤。

FinalResponseValidator 不声称这是官方射程公式；如果后续规则明确距离定义，只需替换 Candidate 范围判断。

---

## 9. 当前主运行链

```text
HTTP Request
 ↓
Pydantic ServerGameResponseDTO
 ↓
GameState
 ↓
World / Strategic Memory
 ↓
Features
 ↓
PolicyGraph (control plane)
 ↓
Strategy
 ↓
CandidateRegistry
 ↓
Legal + Rules
 ↓
Reward / Utility
 ↓
TeamPlanner
 ↓
TeamConflictResolver
 ↓
TeamDecision
 ↓
DomainActionMapper
 ↓
Pydantic Wire Validation
 ↓
FinalResponseValidator
 ↓
LLM / executeCmd top-level guards
 ↓
roleCommandMap JSON
 ↓
HTTP Response
```

下一步最适合补：

```text
HTTP Server Adapter
Request Deadline Middleware
Team-level shared resource conflict
Build/Buy/Sell/Task plugins
Command feedback reliability model
```


---

# 10. Experience 已对齐真实 TeamDecision

旧实现：

```text
Graph Decision
→ Experience
```

真实执行：

```text
TeamDecision
→ FinalResponseValidator
→ roleCommandMap
```

二者可能不一致。

V0.2.9 后只对 **实际通过最终校验并发送** 的 role decision 建立 Experience。

下一回合：

```text
lastRoundRoleActionResults
```

按 actor/weapon id 分别绑定 legality。

团队级 RealizedReward 当前通过：

```text
TeamCreditAssigner
```

在未显式非法的动作之间均分。

这是第一版可替换 credit model；以后可升级为：

```text
marginal contribution
short-horizon simulation
counterfactual credit
Shapley approximation
```

无需修改 ExperienceStore。

---

# 11. HTTP 比赛入口

新增：

```text
python main3.py <port>
```

内部：

```text
0.0.0.0:<port>
        ↓
ThreadingHTTPServer
        ↓
HttpTurnService
        ↓
FortressAgentRuntime
        ↓
roleCommandMap JSON
```

安全边界：

```text
Runtime internal deadline = 3.8s
HTTP outer timeout = 4.6s
game response limit = 5s
```

异常或 outer timeout 时，HTTP 层返回合法空 envelope，而不是 traceback/非法 JSON：

```json
{
  "roleCommandMap": {},
  "prompt": "",
  "executeCmd": ""
}
```

Runtime 有状态，因此 HTTP service 使用 lock 防止并发请求破坏 WorldMemory / Experience / PolicyState。


---

# 12. Competition startup entry

The production entry is the root-level `main3.py`, at the same directory level as `src/`:

```text
project_root/
├── main3.py
└── src/
    ├── agent/server.py
    └── fortress_agent/...
```

The judger may start the submission directly with:

```bash
python main3.py <port>
```

Startup chain:

```text
main3.py
  ↓ resolve project root / chdir
  ↓ add <root>/src to sys.path
  ↓ configure stdout logging
agent.server.serve(port)
  ↓ build_runtime(root_logger)
  ↓ build in-memory WorldMemory / Experience stores
  ↓ route all audit records to the root stdout logger
fortress_agent.server.http.run_http_server
  ↓ bind 0.0.0.0:<port>
```

This path does not require editable installation and does not depend on `run.sh`.


## P0 Traversability Invariant (V0.3.3)

Resource cells are hard obstacles for movement. `stone`, `iron`, and `copper` coordinates are interaction targets, **not walkable cells**. A worker must stand on a cardinally adjacent walkable cell and issue `collect(targetPos=<resource cell>)`.

This invariant is enforced independently by Candidate generation, LegalActionFilter, A* pathfinding, EmergencyPolicy, and FinalResponseValidator. A `move` targeting an active resource cell is never allowed to reach the server.


## V0.3.4 production logging contract

The judging environment exposes only the stdout log from `main3.py`. Production therefore creates no `trace.jsonl`, `io.jsonl`, `experience.jsonl`, `world_events.jsonl`, or snapshot file. All structured audit records flow through the same root logger with a logical `channel` field.
