
## V0.5.8 Team Doctrine / Safe Navigation

V0.5.8 将长期职责从零散 Utility 竞争提升为稳定 Doctrine：主建设者完成三座共享控制点的 Rocket cluster；第二 Worker 开局优先最近 stone；三面墙 16/16 完成后双 Worker 切换高价值矿→出售→升级循环；Pioneer 白天任务、夜前回公共 Rocket 控制点、夜战后继续任务。

夜间 Worker 使用基于 ``RobotThreatField`` 的时间感知 Safe A*，同时考虑机器人朝 Station 的保守进攻线与最近真实运动方向；夜间矿必须通过安全去程、最小安全驻留窗口和安全撤离验证。文本类自进化任务 Prompt 使用中文主导流程，并可通过 ``todo(TEXT_TASK_PROMPT)`` 快速定位修改入口。详见 ``SAFE_NAVIGATION_WALL_DOCTRINE_V0.5.8.md`` 与 ``TEXT_TASK_PROMPT_OPTIMIZATION_V0.5.8.md``。

# FortressAgent V0.5.4 — Task Skill + Combat Ballistics + Economy/Construction Loop

## V0.5.4 — 对战复盘第二轮深挖

本版在 V0.5.3 “任务能执行、夜晚不挂机、Worker 初步分工”基础上继续推进四条闭环：

- M8：TaskPoint 锚定、timeout 上下文、旧 LLM 响应隔离、同类任务成功 SOP 记忆；
- M6：角色-武器站位匹配、Rocket AOE 落点优化、Gatling 最近弹道目标、Railgun 能量穿透；
- M4：矿点候选收敛、背包满载转卖、三塔后 stone 战略保留；
- M5：主建设者武器返场、stone 携带者墙体返场、weapon/wall 建造顺序。

详细说明见 `DEEP_STRATEGY_OPTIMIZATION_V0.5.4.md`。

## 历史版本

## V0.5.3 — 对战复盘第一轮优化

本版本针对 2026-09-19 实战复盘优先修复四个高收益问题：

- 自进化任务新增 `TaskSessionCoordinator`，形成 `acceptTask -> task prompt / executeCmd -> lastCmdResult -> submitAnswer` 跨回合闭环；
- 夜间新增 `DefensePostCandidateGenerator`，角色会先回武器控制位；TeamPlanner 空结果不再吞掉 PolicyGraph Emergency/control decision；
- 开局固定轻量角色分工：最低 ID Worker 负责前三座 Rocket，另一个 Worker 不抢开局武器预算并优先采矿；三座武器后提高 stone/Wall 的战略价值；
- TeamPlanner 在联合移动冲突后会尝试该角色第二/第三候选，不再因为第一候选冲突直接让角色空闲；
- 默认 `prepare_margin=20`，白天结束前 20 回合开始全员回收；
- compact stdout 新增一回合一屏的人类摘要，并显示 PolicyGraph node chain、Gold/Score、最终动作、TaskStage、ExecCmd/LastCmdResult。

详见 `MATCH_REPLAY_OPTIMIZATION_V0.5.3.md`。


> **当前权威说明**：README 下方保留了早期版本的历史变更记录，其中部分旧语义（例如早期的 4-neighbor/cardinal collect、Task 生命周期推断）已经被 V0.5.x 正式规则覆盖。开发与比赛请以 `PROJECT_ARCHITECTURE_GUIDE_ZH.md`、当前 `game_rules/` 和最新测试为准。


本版本基于完整官方接口文档修正协议语义，并将运行时从单动作推进到多角色联合动作。

新增/修正：

- `Role.cooldown`
- `PlayerTask.timeoutRounds`
- `RobotRole.targetTeam`
- current-round `errors` 与累计异常概念分离
- station 2×2 footprint
- sell / buy `num=1` default
- dynamic map-bound validation
- `FinalResponseValidator`
- `LLMBudgetTracker`
- `OutcomeRecord.action_legal`
- `TeamDecision`
- `TeamPlanner`
- `TeamConflictResolver`
- 第一版真实 `AttackAction / Candidate / Reward / Evaluator`
- controller / weapon / cooldown / target-count 联合校验

详见：

```text
OFFICIAL_INTERFACE_ALIGNMENT.md
```


## Competition entrypoint

判题系统直接执行项目根目录下、与 `src/` 同级的 `main3.py`：

```bash
python main3.py <port>
```

监听：

```text
0.0.0.0:<port>
```

HTTP POST 可直接接收官方 Request JSON。


## V0.3.0 — Complex Strategy Architecture

新增：

```text
StrategyGraph
StrategyNode
StrategyActivator
StrategySessionStore
TeamConstraintRegistry

Sell / Buy / Use
AcceptTask
SubmitAnswer provider hook
SummonTreasure provider hook
BuildCatalog / BuildRecipe
StrategicLLMCoordinator
```

复杂策略扩展规范见：

```text
COMPLEX_STRATEGY_EXTENSION.md
```

当前完整测试：

```text
126 tests passed
```

真实 HTTP 冒烟测试：

```text
python main3.py <port>
→ HTTP 200
→ valid roleCommandMap
```


## V0.3.1 — Runtime observability and closed loop

- Unified `correlation_id` across request, DomainEvent, Trace, Experience and Outcome.
- Production observability is consolidated into the single stdout logger configured by `main3.py`.
- IO / Trace / World Events / Experience remain logically separated by the structured `channel` field.
- TeamPlanner reuses the PolicyGraph-selected StrategyProfile so StrategySession advances only once per turn.
- Full real closed-loop walkthrough: `RUNTIME_CLOSED_LOOP_EXAMPLE.md`.
- Runnable example: `scripts/runtime_closed_loop_demo.py`.
- 129 tests pass.


### Entry layout

```text
project_root/
├── main3.py              # competition entrypoint
├── src/
│   ├── agent/
│   │   └── server.py     # exposes serve(port)
│   └── fortress_agent/   # internal application packages
└── tests/                # no production runtime log directory is required
```

`main3.py` resolves the project root, changes the working directory to it, inserts `root/src` into `sys.path`, configures stdout logging, then executes:

```python
from agent.server import serve
serve(port)
```

`run.sh` is retained only as a local convenience wrapper and forwards to `main3.py`; the competition runtime does not depend on it.


## P0 Traversability Invariant (V0.3.3)

Resource cells are hard obstacles for movement. `stone`, `iron`, and `copper` coordinates are interaction targets, **not walkable cells**. A worker must stand on a cardinally adjacent walkable cell and issue `collect(targetPos=<resource cell>)`.

This invariant is enforced independently by Candidate generation, LegalActionFilter, A* pathfinding, EmergencyPolicy, and FinalResponseValidator. A `move` targeting an active resource cell is never allowed to reach the server.


## V0.3.3 P0 movement safety

Resource cells (`stone/iron/copper`) are hard movement obstacles and are collected from an adjacent walkable cell. See `TRAVERSABILITY_SAFETY.md`.


## V0.3.4 — Production single-log observability

The judging environment exposes only the stdout log configured by `main3.py`.
Production therefore uses exactly one logging outlet.

```text
main3.py logging.basicConfig(stdout)
        ↓
root logger
   ├── channel=system
   ├── channel=io
   ├── channel=world_event
   ├── channel=trace
   └── channel=experience
```

`python main3.py <port>` does **not** create runtime JSONL journal files or a
world snapshot file.

See:

```text
SINGLE_LOGGER_OBSERVABILITY.md
```

## V0.3.5 — Python 3.11 compatibility baseline

The competition runtime is pinned to Python 3.11.x:

```toml
requires-python = "==3.11.*"
```

Dataclass container defaults must use `field(default_factory=...)`; direct
`MappingProxyType({})`, `{}`, `[]`, `set()`, `dict()` or `list()` defaults are
forbidden. Run before packaging:

```bash
python scripts/check_python311_compat.py
python -m pytest -q
```


## V0.3.6 — Strategy loop + logger modes

- Pioneer can navigate to tasks under economy instead of local move loops.
- Workers can travel to vendor, shop and base staging ring.
- Prepare can return workers to base and enables build when verified recipes are configured in `main3.py`.
- Defense can emit no command when no action clears `minimum_action_utility`.
- `RuntimeFeedbackMemory` stores action legality, treasure result, `lastCmdResult` and server errors independently of logging.
- `LOG_MODE = "compact" | "full"` is controlled only in `main3.py`; logging mode never changes agent memory.

See `STRATEGY_AND_LOG_REPAIR_V0.3.6.md` and `LOG_MODES.md`.


## V0.3.7 — COMMAND_ERROR self-learning safety

- TaskPoint cells are hard non-walkable interaction terrain.
- Pioneer routes to a task point's adjacent walkable access cell and then issues `acceptTask`.
- Detailed `COMMAND_ERROR` is parsed into agent-visible feedback memory.
- `lastRoundRoleActionResults=false` suppresses exact illegal move retries even without detailed text.
- Learned impassable cells feed Traversability, A*, LegalActionFilter and FinalResponseValidator.
- COMMAND_ERROR details are persisted into Experience Outcome fields.
- New safety lessons trigger one budgeted strategic LLM safety-revision prompt containing the exact hard rule.
- `llm_explore` / `llm_task_search` no longer disable gather/sell/buy/use/build candidate families.

See `COMMAND_ERROR_SELF_LEARNING_V0.3.7.md`.

## V0.3.8 — Authoritative action-failure trigger

`lastRoundRoleActionResults[role_id] == false` is now the primary action-failure trigger. Error text is optional semantic enrichment and no longer needs a literal `[COMMAND_ERROR]` prefix. Compact logs emit `action_execution_failed`; generic failures temporarily suppress the exact action, while parsed `impassable terrain [...]` evidence creates a permanent traversability rule.

See `FEEDBACK_FAILURE_TRIGGER_V0.3.8.md`.


## V0.3.9 — Strict feedback evidence chain

Runtime safety learning no longer relies on any external/judger log line.
`lastRoundRoleActionResults=false` is the primary execution-failure trigger.
A permanent impassable-cell lesson requires an exact match between the failed
role result, the previous action actually sent by this agent, and a received
`errors(errorCode=4).description` for the same MOVE target.

`lastCmdResult` remains in feedback memory but is never parsed as a role MOVE
error. See `STRICT_FEEDBACK_EVIDENCE_V0.3.9.md`.


## V0.4.0 — Dynamic terrain-type rule learning

Permanent movement lessons are now semantic terrain rules, not coordinate
blacklists. A corroborated server failure such as
`impassable terrain [mysteryGate]` learns:

```text
mysteryGate -> traversability=impassable
```

All current/future neutral zones of that type are blocked by TraversabilityMap.
The failed coordinate is retained only as evidence and for short-term exact
retry suppression. See `DYNAMIC_TERRAIN_RULES_V0.4.0.md`.


## V0.4.1 — Team-wide MOVE retry guard

A failed MOVE target is now temporarily suppressed for **all roles**, not only
for the role that first failed. This protects the five-anomaly budget.

```text
role 20011 MOVE(x,y) -> false
        ↓
ALL roles temporarily cannot MOVE(x,y)
```

The temporary coordinate guard remains distinct from permanent semantic terrain
learning (`terrain_type -> impassable`). Configure the temporary duration in
`main3.py` with `MOVE_FAILURE_GLOBAL_BAN_ROUNDS`.

See `GLOBAL_MOVE_RETRY_GUARD_V0.4.1.md`.


## V0.4.2 — Dynamic rule lifecycle

Runtime terrain rules now have explicit `ACTIVE / DORMANT / RETIRED` lifecycle states. Resource-scoped rules become dormant when the resource type disappears from a complete snapshot; task-scoped rules become dormant when the matching task is explicitly invalid or disappears, and can reactivate when the entity returns. Explicit successful-MOVE counter-evidence retires an impassable rule. Only ACTIVE rules affect decisions. See `DYNAMIC_RULE_LIFECYCLE_V0.4.2.md`.

## V0.5.1 station defense build template

Normal maps derive construction areas automatically from the 2x2 station:

```text
222222
211112
210012
210012
211112
222222
```

`0=station`, `1=weapon build ring`, `2=wall build ring`. The 12 weapon cells
share the official global weapon limit of 3. Default opening doctrine prefers
Rocket as the first defensive weapon.


## V0.5.2 — Deadline hardening + architecture documentation

本版本修复真实比赛日志中的 `request timeout -> BrokenPipeError` 链路，并把项目注释/架构说明补齐。

核心变化：

- Runtime internal deadline 默认 3.2s；
- HTTP outer watchdog 默认 4.2s；
- Runtime 放入单 worker executor，完全同步阻塞也能让 HTTP 线程按时降级返回；
- 上一 worker 拖尾时，下一请求立即 busy-fallback，避免连续超时；
- 捕获 BrokenPipe/ConnectionReset，不再由 socketserver 打未处理 Traceback；
- `request timeout` 不再错误归因到上一回合各角色动作 Outcome；
- `find_path_to_any` 改为 single-pass multi-goal A*；
- TeamPlanner 复用 PolicyGraph 的 `viable_actions`，避免重复 Candidate/A*；
- Gatling/Attack candidate 增加目标池/组合上限，避免机器人数量大时组合爆炸；
- 核心抽象类补充“实现位置/注册位置”中文注释。

详细文档：

```text
TIMEOUT_BROKEN_PIPE_ANALYSIS_V0.5.2.md
PROJECT_ARCHITECTURE_GUIDE_ZH.md
```

## V0.5.5：统一辅助决策、夜前墙体节奏与三级日志

- `prompt/executeCmd` 已进入 `AuxiliaryDecision -> AuxiliaryExperience -> AuxiliaryOutcome`；生产路径不再依赖字符串旁路。
- TaskSession 只记录最终确认发送的 sandbox 命令；未送达 HTTP 响应会撤销本轮命令历史。
- Day1/2/3/4+ 夜前最低墙体目标分别为 8/12/16/20；三塔后两个 Worker 同时优先 stone。
- stone 正常以最多 4 个为一批返场，临近夜晚立即返场；prepare 只允许原地 collect，不允许继续远距离追矿。
- 日志改为 LOW / MEDIUM / HIGH；默认 MEDIUM，仅输出人类可读回合块，不再夹杂 JSON trace。

## V0.5.6：可配置策略参数、轻量在线学习与 Utility 公式日志

- 阶段/采矿/搜索宽度等软阈值集中到 `main3.py` + `config/tuning.py`；
- 资源目标默认“距离优先、价值次要”，两项权重可配置；
- 白天早期尽量填满背包，正常阶段尽量采完当前矿；最后 8 回合已在矿旁只额外采 1 次后撤离；
- Runtime Learning 更新周期可配置，只允许小步修改 allowlist 中的软参数，并把真实更新写入回合日志；
- MEDIUM 日志显示被选动作的 `UtilityFormula` 和资源 `ResourceFormula`；
- 官方游戏规则继续保持不可学习常量。

详见 `CONFIG_LEARNING_UTILITY_V0.5.6.md`。

## V0.5.7：Relative Learned Overlay

运行时学习改为 `Effective = Base × (1 + RelativeOverlay)`。学习层只记录相对人工 Base Config 的比例，不再把绝对参数值当作学习状态。例如 Base=4 时 +0.2 会记录为 +5%；Base 改为 8 后同一 Overlay 自动成为 +0.4。当前不启用 JSONL 持久化；每回合日志结尾都会打印完整 `LearnedOverlay` 快照。详见 `RELATIVE_LEARNED_OVERLAY_V0.5.7.md`。
