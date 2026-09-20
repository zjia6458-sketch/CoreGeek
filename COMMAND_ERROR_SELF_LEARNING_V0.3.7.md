> **V0.4.0 update:** coordinate-level permanent blocking described below is historical. V0.4.0 learns `terrain_type -> impassable`; see `DYNAMIC_TERRAIN_RULES_V0.4.0.md`.

# FortressAgent V0.3.7 — COMMAND_ERROR 自学习与 TaskPoint 安全修复

## 1. 事故复现

真实失败：

```text
[COMMAND_ERROR] role 20011 wants MOVE to (23,14),
but target is impassable terrain [defenderTaskPoint1]
```

旧逻辑存在三层问题：

```text
TaskApproachCandidateGenerator
    → 把 task.position 本身作为 A* goal

TraversabilityMap
    → 只把 resource/building 当作 hard obstacle
    → 没有把 *TaskPoint 当作 interaction-only terrain

FeedbackMemory
    → 保存 errorCode / action result
    → 没有把非法 move 转成下一回合 hard rule
```

因此相同非法 move 可以连续重复，最终消耗异常次数。

---

## 2. 第一层：TaskPoint 静态硬规则

V0.3.7 新增：

```python
TASK_ZONE_TYPES = {
    "challengerTaskPoint1",
    "challengerTaskPoint2",
    "defenderTaskPoint1",
    "defenderTaskPoint2",
}
```

所有 TaskPoint 坐标直接加入：

```text
TraversabilityMap.blocked
```

因此：

```text
MOVE -> task point
```

从第一回合开始就是不可能动作，不需要等服务器报错后才学习。

资源格与任务点统一为：

```text
interaction target
!=
walkable target
```

---

## 3. TaskApproach 改为“抵近”，而不是“站上去”

旧逻辑：

```text
Pioneer
  ↓ A*
TaskPoint (23,14)
```

新逻辑：

```text
TaskPoint (23,14)
  ↓ TraversabilityMap.interaction_access_cells()
(23,13) / (24,14) / (23,15) / (22,14)
  ↓ 过滤 hard obstacles
A* 找最近可达 access cell
```

当 Pioneer 已处于：

```text
(23,13)
```

且 TaskPoint 为：

```text
(23,14)
```

则：

```text
TaskApproachCandidateGenerator -> 不再生成 move
AcceptTaskCandidateGenerator   -> 生成 acceptTask
```

`BasicLegalActionFilter`、`AcceptTaskRewardModel` 与
`FinalResponseValidator` 同步改为四邻接交互语义。

真实 `main3.py` 验证：

```json
{
  "roleCommandMap": {
    "20011": {
      "action": "acceptTask"
    }
  }
}
```

而不会再出现：

```text
move -> (23,14)
```

---

## 4. 第二层：COMMAND_ERROR 解析为 Agent Memory

`RuntimeFeedbackMemory` 现在解析：

```text
[COMMAND_ERROR]
role <id> wants MOVE to (<x>,<y>),
but target is impassable terrain [<terrain>]
```

形成：

```python
CommandErrorLesson(
    role_id="20011",
    action="MOVE",
    target_x=23,
    target_y=14,
    terrain="defenderTaskPoint1",
    reason="impassable_terrain",
)
```

Memory 同时建立两个约束：

```text
Global learned impassable cell:
    (23,14)

Role-specific retry ban:
    (20011, MOVE, 23,14)
```

其中 global block 的意义是：

> 服务器已经证明这个格子不可通行，就不能只禁止 20011；其他角色也不能再拿异常次数重复验证。

---

## 5. 即使没有详细 COMMAND_ERROR，也禁止原样重试

如果服务器只返回：

```json
"lastRoundRoleActionResults": {
  "20011": false
}
```

但没有详细 description，Runtime 会用上一回合真正发送的 Experience：

```text
Experience.action = MOVE(23,14)
```

建立：

```text
role-specific exact retry ban
```

因此：

```text
false feedback
→ 不能原样重发同一个 MOVE
```

这解决了“错误反馈到了，但策略完全不响应”的根因 B。

---

## 6. 安全教训进入四个决策层

新 learned rule 不只是 Memory 数据，而会进入：

```text
1. Candidate / A* Traversability
2. BasicLegalActionFilter
3. FinalResponseValidator
4. Strategic LLM hard-system prompt
```

因此安全顺序是：

```text
Candidate 不生成
    ↓
Legal 再拒绝
    ↓
FinalValidator 最终兜底
```

即使一个未来的新 Strategy Plugin 忽略前两层，FinalValidator 仍会拦截：

```text
repeat_known_illegal_move
move_target_blocked
```

---

## 7. System Prompt 自学习规则

所有战略 Prompt 现在固定包含：

```text
HARD SYSTEM SAFETY RULES:
- Never recommend MOVE onto stone/iron/copper resource cells.
- Never recommend MOVE onto challengerTaskPoint*/defenderTaskPoint* cells.
- Resource cells and task-point cells are interaction-only impassable terrain.
- A COMMAND_ERROR or lastRoundRoleActionResults=false is authoritative negative feedback.
```

并动态追加真实教训，例如：

```text
[COMMAND_ERROR] role 20011 wants MOVE to (23,14),
but target is impassable terrain [defenderTaskPoint1]
=> NEVER MOVE to (23,14); approach an adjacent walkable interaction cell instead.
```

### COMMAND_ERROR 会触发一次安全重分析

如果出现新的安全教训：

```text
new CommandErrorLesson
+
白天
+
非 active task
+
LLM normal budget available
```

则：

```text
StrategicLLMCoordinator
→ one-shot safety revision prompt
```

该 prompt 只对同一个 lesson signature 发送一次。

重要：

```text
Deterministic hard guard
不依赖 LLM 是否成功调用。
```

即使额度耗尽，非法 move 仍立即被阻止。

---

## 8. COMMAND_ERROR 进入 Experience

`OutcomeRecord` 新增：

```python
server_error_messages: tuple[str, ...]
command_error_signatures: tuple[str, ...]
```

以前只知道：

```text
errorCode = 4
```

现在 Experience 可以知道：

```text
哪个角色
什么动作
哪个 target
为什么失败
服务器认定了什么 terrain
```

所以：

```text
Experience
= action
+ predicted utility
+ legal/illegal result
+ detailed server failure reason
```

后续 Replay / Learner / 人工分析都不再丢失最重要的错误语义。

---

## 9. Compact Logger 仍保留该证据

即使：

```python
LOG_MODE = "compact"
```

也不会丢掉：

```text
command_error_learned
server_feedback_observed
outcome
```

实际日志：

```json
{
  "kind":"command_error_learned",
  "data":{
    "role_id":"20011",
    "action":"MOVE",
    "target":[23,14],
    "terrain":"defenderTaskPoint1",
    "reason":"impassable_terrain",
    "hard_rule":"... NEVER MOVE to (23,14) ..."
  }
}
```

Memory 内容仍与 FULL/COMPACT 完全无关。

---

## 10. LLM advisory 不再关闭经济能力

你日志中另一个问题是：

```text
llm_explore
→ tags 只有 explore/task/treasure
→ gather/sell/buy/build 全被裁掉
```

这违背了：

```text
LLM = advisor
not action controller
```

V0.3.7 修改为：

```text
llm_explore / llm_task_search
仍保留：
move
explore
task
treasure
gather
sell
buy
use
build
```

LLM advisory 通过 Utility bias 改变优先级，而不再直接封死基础经济动作空间。

`build` 是否真正产生仍由 `main3.py` 中已验证 `BUILD_RECIPES` 决定；没有真实配方时继续安全禁用，不使用异常次数试错。

---

## 11. 本次事故对应的新安全闭环

```text
Server Response r16
    ↓
errors[4].description
    ↓
RuntimeFeedbackMemory.observe()
    ↓
CommandErrorLesson
    ├── global impassable (23,14)
    ├── exact retry ban 20011→(23,14)
    ├── Experience Outcome detail
    ├── compact log command_error_learned
    └── LLM safety-revision prompt
            ↓
next PolicyContext.feedback_memory
            ↓
Traversability / Pathfinder / Legal / FinalValidator
            ↓
MOVE(23,14) impossible
```

这套机制适用于未来尚未建模的其它不可通行 terrain，不局限于 TaskPoint。
