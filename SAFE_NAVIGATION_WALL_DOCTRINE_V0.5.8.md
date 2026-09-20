# FortressAgent V0.5.8：夜间安全导航、机器人路线识别与三面墙 Doctrine

## 1. 本版本解决的问题

V0.5.8 将夜间 Worker 采矿与围墙施工从“普通 Utility 偏好”提升为具有硬约束的策略模块，主要解决：

1. 夜间不能只根据机器人当前坐标判断安全；机器人每回合都会推进，当前安全格可能在 Worker 到达时已经进入攻击范围。
2. 普通 A* 只优化几何距离，不能表达“短路经过机器人未来进攻走廊，而稍长路线更安全”。
3. Worker 到达矿点以后还需要停留 collect；只验证去程而不验证驻留/撤离，会出现“刚到矿就被封路”。
4. 围墙如果只依靠 Utility 随机选择邻接格，会出现施工顺序漂移、数量不足以及 Worker 走向 A 却在 B 建墙。
5. 资源目标和路径是两个不同概念：矿点应尽量保持稳定，但机器人移动时路径必须允许动态重规划。

---

## 2. 普通 A* 与 Safe A* 的职责

### 2.1 白天：普通 A*

白天资源采集、任务接近、商店接近等仍使用普通 `AStarPathfinder`：

```text
起点
  ↓
TraversabilityMap
  ↓
Chebyshev A*
  ↓
最短合法路径
```

白天没有机器人持续追击压力，不应让全部导航都承担时间维度威胁计算的开销。

### 2.2 夜间：Safe A*

夜间 Worker 采矿、危险 Worker 撤离以及 Pioneer 返回 Rocket 公共控制位使用：

```text
RobotTrajectoryMemory
        +
RobotThreatField
        ↓
SafePathPlanner
        ↓
(x, y, ETA) 时间维度 A*
```

Safe A* 的状态不是单纯 `(x,y)`，而是：

```text
(x, y, eta)
```

因为同一个格子现在可能安全，但 4 回合后机器人已经到达。

单步代价为：

```text
step_cost
= 1
+ night_threat_path_weight × predicted_risk
+ unknown_cell_cost
```

若：

```text
predicted_risk >= night_hard_risk_threshold
```

该节点直接不允许扩展，而不是只扣 Utility。

---

## 3. RobotThreatField：机器人路线如何识别

比赛协议提供机器人全局位置，但不提供服务器内部 PathFinder，因此 Agent 不声称能够精确复刻机器人路线。

V0.5.8 使用两条预测路线的风险并集。

### 3.1 路线 A：朝 Station 的最快进攻路线

每台机器人每回合最多移动一格，因此以 Chebyshev 最短方式向己方 2×2 Station footprint 收缩：

```text
Robot
  ↘
   ↘
    Station
```

这是偏保守的“最快到达基地”预测。

### 3.2 路线 B：最近真实移动方向

新增：

```text
RobotTrajectoryMemory
```

每回合记录最近真实机器人位置，例如：

```text
R80: (14, 13)
R81: (13, 14)
```

得到最近真实 heading：

```text
(-1, +1)
```

未来若干步同时外推该方向：

```text
Observed heading
      ↓
最近真实绕行方向
```

随后再重新向 Station 收缩。

因此机器人如果因为墙、单位拥堵等原因开始绕行，威胁场不会继续只相信理想直线。

### 3.3 为什么使用并集，而不是二选一

不能因为上一回合机器人向左走，就认定下一回合一定继续向左；同样不能因为理论最短线向右，就忽略它刚刚真实发生的绕行。

所以：

```text
Threat = max(
    Station-route threat,
    Observed-heading-route threat
)
```

宁可保守拒绝一个矿，也不把 Worker 送进可能的机器人走廊。

---

## 4. 风险半径

每个预测机器人位置都会扩张：

```text
hard_radius = attackRange + hard_safety_margin
soft_radius = attackRange + soft_safety_margin
```

默认：

```text
hard margin = 1
soft margin = 3
```

含义：

- hard 内：绝不进入；
- hard 与 soft 之间：允许 A* 评估，但路径成本显著增加；
- soft 外：视为低风险。

所有数字均在 `main3.py` 配置，不散落在业务模块。

---

## 5. 夜间一个矿点要通过哪些安全检查

`night_resource_route()` 必须同时满足：

```text
1. Worker HP >= night_worker_min_hp_ratio
2. Resource 位于 night_edge_mining_margin_cells 边缘带
3. 存在安全 approach interaction cell
4. Safe A* 可以到达
5. 到达时风险 <= night_resource_max_risk
6. 到达后至少保持 night_resource_min_safe_hold_rounds 个安全回合
7. 驻留窗口结束后仍能撤往低风险边缘 sanctuary
```

只有全部通过，该资源才进入 Candidate。

因此：

```text
高价矿 + 不安全路线
```

不会因为 Utility 高而被选择，因为它根本没有 Candidate。

---

## 6. collect 也必须重新验证安全

Worker 已经到矿旁并不代表可以无限 collect。

每一回合 `night_gather_is_safe()` 都重新检查：

```text
本回合 collect
        ↓
Worker 原地停留一回合
        ↓
ETA=1 是否仍安全？
        ↓
下一回合是否仍可进入安全边缘/安全撤离路线？
```

若机器人逼近：

```text
Gather Candidate 消失
        ↓
NightWorkerRetreatCandidate
        ↓
Safe A* 撤离
```

安全高于“把当前矿采完”的 commitment。

---

## 7. 资源目标稳定与路径动态重规划

新增/强化：

```text
MiningRuntimeMemory
```

Worker 一旦真正发送去矿动作，至少在配置的 commitment window 内保持同一矿点：

```text
resource_commitment_min_rounds
```

但 commitment 只锁“目标矿”，不锁具体路径。

正确行为是：

```text
目标：stone A   ← 保持稳定
路径：P1→P2→P3 ← 可以因为 Robot 每回合变化而重新 Safe A*
```

不是：

```text
A → B → A → B
```

也不是：

```text
Robot 已经封路仍坚持旧路径
```

如果旧矿变危险，安全条件拥有最高优先级，可以立即释放 commitment。

---

# 8. 三面墙 Blueprint

用户策略要求：

### 左上/左半图基地

```text
建设：TOP + BOTTOM + RIGHT
后侧 LEFT 保留出入口
```

### 右下/右半图基地

```text
建设：TOP + BOTTOM + LEFT
后侧 RIGHT 保留出入口
```

对于标准 2×2 Station + distance=2 wall ring：

```text
三面墙 Blueprint = 16 格
```

不是 20 格整圈。

---

## 9. 围墙建设顺序

`ordered_wall_build_cells()` 为唯一权威施工顺序：

```text
第一阶段：迎敌侧中间 4 格
    ↓
优先形成正面完整阻挡

第二阶段：迎敌侧两个角
    ↓
完成完整迎敌侧 6 格

第三阶段：TOP/BOTTOM 交替
    ↓
从迎敌侧逐步向后方延伸
```

形式上：

```text
front-center
front-center
front-outer
front-outer
front-top-corner
front-bottom-corner
TOP/BOTTOM 交替向 rear 推进
```

而不是按 `(x,y)` 字典序随机建。

---

## 10. BuildCandidate 与返场目标共享顺序

以前可能出现：

```text
WallBuildApproach → 去 A
到达以后 BuildCandidate → 发现 B utility 高
→ 在 B 建
```

V0.5.8 中二者都读取：

```text
ordered_wall_build_cells()
```

并只检查前：

```text
build_target_lookahead
```

个缺口。

所以“走向哪里”和“落墙在哪里”保持一致。

---

## 11. 围墙数量保证

主动防御阶段的完成条件不再是：

```text
wall_count >= 某个较低的每日软目标
```

而是：

```text
wall_blueprint_missing_count == 0
```

即标准地图需要：

```text
16 / 16 planned walls
```

才允许把“墙体建设阶段”视为完成。

因此两个 Worker 不会在 12 面墙时就主动切换到高价值矿经济。

如果地图当时没有 stone，Agent 可以利用空档处理其它安全事务；一旦 stone 可用，未完成 Blueprint 仍保持最高建设需求。

---

## 12. 特殊地图显式配置仍然有效

默认地图使用 Station 0/1/2 模板 + 三面墙 Doctrine。

但显式：

```text
weapon_build_cells
wall_build_cells
```

属于更具体的特殊地图证据，优先于 Station ring 自动分类。

这样策略升级不会破坏已有比赛 fixture 或未来特殊地图。

---

## 13. 主要配置项

位于根目录 `main3.py`：

```text
NIGHT_EDGE_MINING_MARGIN_CELLS
NIGHT_ROBOT_PREDICTION_HORIZON
NIGHT_ROBOT_OBSERVED_HEADING_STEPS
NIGHT_ROBOT_HARD_SAFETY_MARGIN
NIGHT_ROBOT_SOFT_SAFETY_MARGIN
NIGHT_SAFE_PATH_MAX_STEPS
NIGHT_WORKER_MIN_HP_RATIO
NIGHT_RESOURCE_MIN_SAFE_HOLD_ROUNDS

NIGHT_THREAT_PATH_WEIGHT
NIGHT_HARD_RISK_THRESHOLD
NIGHT_RESOURCE_MAX_RISK
NIGHT_ESCAPE_MAX_RISK
NIGHT_RESOURCE_SAFETY_WEIGHT
NIGHT_RESOURCE_DISTANCE_WEIGHT
NIGHT_RESOURCE_VALUE_WEIGHT

WALL_DAY1_TARGET
WALL_TARGET_INCREMENT_PER_DAY
WALL_TARGET_MAX
BUILD_TARGET_LOOKAHEAD
RESOURCE_COMMITMENT_MIN_ROUNDS
```

这些都是我方策略软参数；机器人攻击距离、昼夜长度、建筑上限等官方事实不会被 Runtime Learning 修改。

---

## 14. 当前局限

1. RobotThreatField 是保守预测，不是服务器内部寻路器复制品。
2. 当前不模拟“机器人花几回合打穿某一面墙”的精确 breach time，因此 fastest-station route 会偏保守。
3. Safe A* 当前不显式加入 WAIT 节点；如果最优策略是原地等机器人经过，本回合可以通过“不发 Worker move”实现，但多步规划不会主动把 WAIT 编入路径。
4. 多机器人风险取最大值，尚未建立围堵概率模型；这是安全优先的设计。

这些局限不会使 Unsafe path 被当作已知安全；主要代价是可能放弃部分本来勉强可采的夜间矿。
