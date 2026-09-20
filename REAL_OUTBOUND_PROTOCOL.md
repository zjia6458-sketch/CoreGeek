# FortressAgent V0.2.8 — Real Outbound Protocol

## 1. 服务器真实响应格式

现在统一输出：

```json
{
  "roleCommandMap": {
    "<roleId>": {
      "action": "..."
    }
  },
  "prompt": "",
  "executeCmd": ""
}
```

`roleCommandMap` 是角色 ID → 单条命令的映射。

因此同一回合可以同时给多个不同角色下发命令，但同一个角色不能出现两次。

> JSON object 不支持重复 key。示例中重复出现 `"10010"`、`"10011"`、`"10012"` 只是不同 action 的演示，不能组合成同一个实际 JSON。

正确多角色形式例如：

```json
{
  "roleCommandMap": {
    "10010": {"action": "move", "...": "..."},
    "10020": {"action": "attack", "...": "..."},
    "10011": {"action": "sell", "...": "..."}
  }
}
```

---

## 2. 已实现命令

```text
move
attack
sell
buy
build
remove
acceptTask
submitAnswer
summonTreasure
use
drop
collect
```

所有命令使用 discriminated union：

```text
action
↓
选择对应 Pydantic Command Model
```

未知 action 会被拒绝。

---

## 3. 必填非空字段

以下字段不能发送空值：

```text
move.targetPos
attack.controllerId
attack.targetPos

sell.name / sell.num
buy.name / buy.num

build.name / build.targetPos
remove.targetPos

submitAnswer.taskAnswer

summonTreasure.targetPos
summonTreasure.item

use.name

drop.name

collect.targetPos
```

其中：

```text
targetPos
item
```

至少包含一项。

`num > 0`。

所有坐标：

```text
0 <= x <= 40
0 <= y <= 31
```

---

## 4. 可为空字段

根据真实格式与命令语义：

```text
prompt
executeCmd
```

允许：

```text
""
null
```

内部统一为 `""`。

`use.targetPos` 为可选：

```text
Medicine
SmallRobotSummonOrder
```

可以没有 targetPos；

而：

```text
WallFixer
DizzyWeapon
Bomb
WeaponUpgradeVoucher
```

可以携带 targetPos。

具体物品是否“必须有 targetPos”属于更高层 Rule/Validator，而不是 Wire Schema 猜测。

---

## 5. 两层兜底

### Field-level fallback

任何必填字段非法：

```text
Pydantic validation failure
```

命令不会进入最终 `roleCommandMap`。

### Role-level fallback

```text
invalid desired command
        ↓
RoleCommandFallbackResolver
        ↓
known-good emergency command ?
     /                     \
   yes                      no
    ↓                        ↓
replace                  omit role
```

默认：

```text
OmitInvalidRoleCommandFallback
```

不创造 WAIT，也不创造未知安全性的 move。

如果 Safety 层已经预先计算出确认合法的 emergency action，可以通过：

```text
StaticRoleCommandFallback
```

注入。

fallback 本身还会再次经过同一个 Pydantic Schema；fallback 非法时仍然丢弃。

---

## 6. 为什么允许空 roleCommandMap

协议层的最高原则是：

```text
invalid command
>
no command
```

风险更高。

因此：

```json
{
  "roleCommandMap": {},
  "prompt": "",
  "executeCmd": ""
}
```

在 Wire Schema 中允许构造。

如果比赛官方随后明确“每回合至少一个角色必须有命令”，这个限制应加在 `FinalResponseValidator`，并由 EmergencyPolicy 保证产生至少一条合法命令。

---

## 7. Domain Action 映射

当前真实映射：

```text
MoveAction
ExploreAction
    ↓
move

GatherAction
    ↓
WorldMemory.resource position
    ↓
collect
```

特别是 Gather 不再把内部 `resource_id` 发给服务器，因为真实协议只接受：

```text
collect.targetPos
```

---

## 8. 多角色联合决策

Wire 层现在天然支持：

```text
roleCommandMap = N commands
```

目前 `PolicyGraph` 仍返回一个 `Decision`，所以 `DecisionResponseEncoder` 先生成单角色 map。

同时提供：

```python
encode_role_commands(...)
```

支持批量命令。

下一步 Team Planner 可以演进为：

```text
TeamDecision
    ├── worker 10010 → collect
    ├── pioneer 10011 → acceptTask
    └── gatling 10020 → attack
```

而不需要再次修改 Outbound Protocol。

---

## 9. 仍应放在业务 Rule 的约束

Wire Schema 只负责“JSON 形状正确”。

以下内容不能只靠 Pydantic：

```text
白天能否 attack
谁可以 build
controllerId 是否有效
attack target 是否在射程
rocket cooldown
build cell occupancy
inventory 是否真的有 item
gold 是否足够 buy
task 是否处于可 accept 状态
```

这些继续由：

```text
LegalActionFilter
HardRule
StateValidator
FinalValidator
```

负责。
