# FortressAgent V0.2.7 — Real Server Protocol & Structured LLM Strategy

## 1. 真实服务器 Response 已正式进入协议层

当前协议链：

```text
Raw response
    ↓
ServerGameResponseDTO (Pydantic)
    ↓
GameStateBuilder.build_server()
    ↓
Normalized GameState
```

真实字段：

```text
roundNo
mapInfo
teamOur
teamEnemy
robot
phaseTask
lastRoundRoleActionResults
lastSummonTreasureResult
llmResp
worldNews
lastCmdResult
vendorShopList
weaponShopList
errors
```

策略层不直接读取这些 camelCase 字段。

---

## 2. Round → Day / Phase

服务器示例没有显式 day/night，因此按正式比赛周期推导：

```text
70 turns day
60 turns night
130 turns / day
```

例如：

```text
roundNo = 85

day = 1
phase = night
phase_round = 15
turns_until_phase_change = 45
```

该逻辑集中在 Protocol Builder，不进入 Strategy。

---

## 3. teamOur.roles 的规范化

服务器将人物、基地、武器、防墙全部放进：

```text
teamOur.roles
```

内部拆成：

```text
characters:
    worker
    pioneer

buildings:
    station
    gatling
    railgun
    rocket
    wall
```

Enemy team 同样拆分。

---

## 4. robot.roles

机器人协议只有：

```text
id
pos
roleType
health
abnormalState
```

其攻击与计分采用比赛规则中的静态常量映射：

```text
smallRobot   attack=5  max_hp=40  score=1
middleRobot  attack=10 max_hp=60  score=2
largeRobot   attack=20 max_hp=500 score=4
bossRobot    attack=40 max_hp=800 score=10
```

---

## 5. mapInfo.zones

Zones 进入：

```text
NeutralZoneState
```

其中：

```text
stone
iron
copper
```

同时转换成 `ResourceNodeState`。

资源没有服务端 ID，因此使用稳定合成 ID：

```text
zone:iron:25:10
```

`mapInfo.zones` 在当前协议适配器中视为完整 neutral-zone snapshot。

因此旧资源如果从后续完整 mapInfo 中消失，可以产生：

```text
ResourceDepleted
```

这与早期“局部视野 response”模式不同。

---

# 6. 民间传说的处理原则

示例：

```text
西部有一石门，门需三钥
南边渡口最近水位下降
```

不能直接转换成：

```text
立即向西移动
```

正确流程：

```text
folkLegends raw text
    ↓
LoreMemory
    ↓
LLM long-horizon analysis
    ↓
Pydantic StrategicAdvisory
    ↓
StrategicMemory
    ↓
StrategySelector bias
    ↓
Reward directional bias
```

LLM 不进入动作协议层。

---

# 7. LLM 输出必须结构化

唯一允许进入 Strategy 的 LLM 输出：

```text
StrategicAdvisory
```

Schema：

```json
{
  "schema_version": "1.0",
  "source_round": 85,
  "recommended_mode": "explore",
  "mode_strength": 0.8,
  "confidence": 0.6,
  "expires_after_rounds": 130,
  "claims": [],
  "objectives": [],
  "short_reason": ""
}
```

配置：

```python
ConfigDict(
    extra="forbid",
    strict=True,
    frozen=True,
)
```

所以：

```text
free-form prose
unknown fields
command injection fields
invalid enum
out-of-range confidence
```

全部无法进入 StrategicMemory。

---

# 8. LLM 不是最高优先级 Policy

有效强度：

```text
effective_strength
=
confidence × mode_strength
```

只有超过阈值才产生 Strategy Bias。

并且顺序固定：

```text
Night Defense
    >
Prepare Deadline
    >
Validated LLM Advisory
    >
Immediate Gather
    >
Default Explore
```

因此 LLM 永远不能覆盖：

```text
night hard defense
deadline
legal filter
validator
emergency safety
```

---

# 9. LLM 对民间传说的推荐作用

对于示例传说，合理的结构化结果可能包含：

```text
Claim:
stone gate located in west
confidence = medium/low

Claim:
stone gate requires three keys

Objective:
explore_region = west
```

但它仍然是：

```text
Hypothesis / Advisory
```

不是：

```text
Fact / Command
```

当前 `ExplorationRewardModel` 会读取经过验证的：

```text
explore_region=west
```

对向西探索动作增加有限 bonus。

因此它改变：

```text
动作排序偏好
```

而不是：

```text
跳过 Candidate / Legal / Reward / Validator
```

---

# 10. LLM Response Error Handling

```text
llmResp
    ↓
StrategicLLMResponseParser
       ├── valid → StrategicMemory
       └── invalid → Trace rejection + ignore
```

错误的 LLM JSON 不会：

```text
抛出到主比赛循环
污染 PolicyState
产生 Action
```

---

# 11. Prompt Contract

框架同时提供：

```python
runtime.build_strategic_llm_prompt(state)
```

Prompt 明确要求：

```text
JSON only
no game commands
long-horizon analysis only
folk legends are uncertain evidence
```

实际 LLM Provider 可以后续作为 Plugin 注入。

---

# 12. 当前重要边界

现在已经确认了真实 State Protocol。

但尚未看到真实 Command Request schema，因此：

```text
Attack / Build / Task / Trade
```

的 wire command 仍不应猜测。

下一份真实 command 示例到来后，应优先进行：

```text
Outbound Wire Schema Alignment
```

然后才能安全启用夜间战斗与完整任务插件。
