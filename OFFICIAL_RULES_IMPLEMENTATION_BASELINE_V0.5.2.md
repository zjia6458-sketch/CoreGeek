# FortressAgent V0.5.2 官方规则实现基线

本文用于区分三种状态：

- **FROZEN**：基础规则已经确定，后续模块不得自行重新解释；
- **IMPLEMENTED**：已有基础实现，但策略质量仍可升级；
- **NEXT MODULE**：正式规则已明确，但高阶策略尚未完成，应按模块继续实现。

## 1. 已冻结的基础规则

### 地图与几何

- 地图边界来自 `MapInfo.width/height`，不在业务代码硬编码 41×32；
- 角色移动 8 方向；
- 距离统一使用 Chebyshev distance；
- 资源、TaskPoint、Vendor、WeaponShop、角色、机器人、建筑均可构成移动阻挡；
- TaskPoint 是永久物理地图障碍，任务内容失效不意味着 TaskPoint 可走；
- 建筑被拆除后是否可通行由下一回合权威 GameState/Occupancy 更新决定；
- World visibility 基于己方单位共享视野半径 4。

状态：**FROZEN**。

### Station build layout

2×2 Station 周围：

```text
222222
211112
210012
210012
211112
222222
```

- `0`：Station footprint；
- `1`：Weapon build zone；
- `2`：Wall build zone；
- Weapon 全局最多 3；
- Wall 最多 20；
- Wall 建造 stone×1；
- Gatling/Railgun/Rocket 建造 25 gold；
- 默认 opening doctrine 第一座武器偏好 Rocket，但这是 Strategy/Reward 偏好，不是硬规则。

状态：**FROZEN + IMPLEMENTED**。

### 时间

- Day 70 rounds；
- Night 60 rounds；
- 10 days / 1300 rounds。

状态：**FROZEN**。

### 基础角色

- Pioneer：HP 200，Backpack 40；
- Worker：HP 220，Backpack 100，2 名；
- 死亡后第二天白天开始后 20 回合可复活，背包保留。

状态：基础字段已对齐；复活策略仍属于后续策略模块。

### Weapon 基础属性

Gatling：

```text
L1 range 3, bullet 1
L2 range 5, bullet 2
L3 range 7, bullet 3
10 damage / bullet
same 90° cone
```

Railgun：

```text
range 6/8/10
energy 10/20/30
single target point
penetrating line
```

Rocket：

```text
range 10/15/global
20 center + 10 splash
1/2/3 target points by level
cooldown 3
```

控制角色必须位于 weapon 周围 1 格。

状态：合法性基础已实现；精确弹道/伤害最优组合属于 M6。

## 2. 执行失败与异常

正式区分：

```text
响应超时 / 响应格式错误 / 指令结构非法
= Response/Command anomaly
```

```text
移动碰撞 / 攻击落点无目标 / 合法动作未生效
= Action execution failure
```

二者不能混为一谈。

V0.5.2 新增：

- request timeout 不再归因给上一角色动作；
- HTTP watchdog；
- BrokenPipe 清理；
- busy fallback；
- pending Experience abandon。

状态：**FROZEN + IMPLEMENTED**。

## 3. 动态反馈规则

### Generic MOVE failure

```text
MOVE(x,y) -> lastRoundRoleActionResults=false
```

短期：全角色暂时禁止 MOVE(x,y)。

### Semantic terrain failure

严格匹配：

```text
previous actual action
+
role_action_results=false
+
received server_errors exact same role/action/target
+
impassable terrain [T]
```

长期学习：

```text
terrain T -> traversability=impassable
```

坐标只作为 evidence。

状态：**FROZEN + IMPLEMENTED**。

## 4. 已实现但仍需策略升级

### Economy

已有：

- Gather；
- ResourceApproach；
- VendorApproach；
- Sell；
- WeaponShopApproach；
- Buy/Use 基础候选。

尚需 M4：

- 基于新闻的矿价周期预测；
- 背包容量规划；
- 多 Worker 分工；
- 10 次矿刷新与路线重新规划；
- “采集→Vendor→建设/升级”的完整经济闭环优化。

### Construction

已有：

- Station 0/1/2 build zones；
- 官方 cost；
- weapon/wall count hard constraints；
- Rocket opening preference。

尚需 M5：

- 防御布局评分；
- 留出 controller 通道；
- Wall 封堵方向；
- Weapon 换型/覆盖时机；
- 建造、升级、修复的资金联动。

### Combat

已有：

- night-only；
- controller adjacency；
- range/cooldown/target count；
- Gatling 90° 基础约束；
- candidate explosion cap。

尚需 M6：

- 几何弹道精确求交；
- Gatling 最近机器人命中模拟；
- Railgun energy penetration；
- Rocket splash overlap；
- 多武器联合 kill optimization；
- Controller assignment optimization。

### Item / Upgrade

正式规则已经明确商品价格和效果。

尚需 M7：

- Voucher level matching；
- Station/Wall/Weapon upgrade planning；
- WallFixer；
- Medicine；
- DizzyWeapon/Bomb；
- summon order 每天最多 10 张；
- 对敌方未来 wave 的经济攻击策略。

### Self-evolution task

尚需 M8：

```text
Approach
→ Accept
→ Understand
→ ExecuteSandbox
→ InspectResult
→ SubmitAnswer
→ Outcome
→ SOP/Skill reuse
```

同时处理：

- timeoutRounds；
- 离开 TaskPoint 周围 1 格任务结束；
- Pioneer death；
- 30 rounds refresh；
- task LLM quota exemption；
- executeCmd 15s sandbox timeout 与 HTTP 5s 决策超时的分离。

### News / Treasure

尚需 M9：

- officialNews → resource price temporal rule；
- folkLegends 多日记忆；
- 宝藏位置/时间/献祭 multiset 推理；
- summon result 2/3/4 的约束更新；
- 宝藏只存在一个的全局状态。

## 5. 后续固定升级顺序

```text
Foundation 已冻结
    ↓
M3 Team Movement & Collision
    ↓
M4 Economy
    ↓
M5 Construction
    ↓
M6 Exact Combat
    ↓
M7 Shop / Item / Upgrade
    ↓
M8 Self-Evolution Task
    ↓
M9 News / Treasure
    ↓
M10 TeamStrategyPlan / RoleIntent
    ↓
M11 Reward / Learning
    ↓
M12 Replay / Competition Hardening
```

开发新模块时必须复用：

```text
game_rules
Traversability
BuildAreaPolicy
Deadline
FinalResponseValidator
RuntimeFeedbackMemory
```

不得在新模块内部复制一套不同口径。

---

## V0.5.4 实现状态补充

在不改变本文件“官方规则基线”的前提下，V0.5.4 对以下演进模块做了实现推进：

- M4 Economy：Worker 职责、矿点候选收敛、80% 背包水位、三塔后 stone 保留；
- M5 Construction：WeaponBuildApproach、WallBuildApproach、内向优先施工顺序；
- M6 Combat：Rocket AOE、Gatling 最近弹道机器人、Railgun 能量穿透、角色-武器站位匹配；
- M8 Self-Evolution：TaskPoint Anchor、timeout context、stale llmResp guard、TaskSkillMemory。

其中“朝地图中心优先施工”“Worker 角色分工”等属于策略启发式，不属于官方硬规则；官方合法性仍由 Game Rules / Legal / FinalValidator 三层约束。
