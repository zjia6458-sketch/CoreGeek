# FortressAgent V0.5.6：策略配置、运行时轻量学习与 Utility 透明化

## 1. 本版本解决什么问题

V0.5.6 的目标不是继续堆叠局部 `if/else`，而是把过去分散在候选生成器、Reward、Strategy、Runtime 中的“策略软数字”集中到显式配置，并把它们分成三类：

1. **阶段阈值（thresholds）**：决定什么时候切换行为阶段，例如 `prepare`、建墙施工预留、采矿紧急撤离、背包高水位等。
2. **策略参数（parameters）**：参与候选评分或 Reward shaping，例如“距离权重”“矿价权重”“当前矿黏性奖励”。
3. **Utility 倍率（utility weight multipliers）**：对 StrategyProfile 给出的基准 Utility 权重做运行时小幅修正。

官方游戏硬规则不属于可学习配置。例如昼/夜长度、Rocket 伤害、武器数量上限、围墙上限、建筑价格、角色属性都仍由 `game_rules` 固定表达，运行时学习器不能修改。

---

## 2. 生产配置入口

生产环境只需要修改仓库根目录的 `main3.py`。该文件现在是策略参数的唯一显式入口之一，并为每个参数附带中文说明。

### 2.1 阶段与采矿阈值

| 配置 | 默认值 | 作用 |
|---|---:|---|
| `PREPARE_MARGIN_ROUNDS` | 20 | 距离黑夜剩余多少回合进入 prepare。prepare 主要负责回基地与武器控制位站位。 |
| `WALL_BUILD_RESERVE_ROUNDS` | 25 | 为把已采矿物真正转成围墙而预留的施工窗口。它可以早于 prepare。 |
| `MINING_EMERGENCY_ROUNDS` | 8 | 采矿紧急窗口。进入后不再开启新矿；已贴着矿的 Worker 最多额外采 1 次，然后离开。 |
| `EARLY_DAY_FULL_BACKPACK_ROUNDS` | 30 | 白天开始后的“填包优先”阶段。该阶段即使超过普通背包高水位也可继续采矿。 |
| `BACKPACK_HIGH_WATERMARK_RATIO` | 0.80 | 非白天早期时，背包达到该占用率后停止开启新的远距离采矿行程。 |
| `NEAR_NIGHT_MINERAL_RETURN_RATIO` | 0.35 | 进入施工预留窗口后，矿物占背包达到该比例就返场施工/变现。 |
| `STONE_BATCH_SIZE` | 4 | 正常阶段 stone 批量运输目标，避免采 1 块就往返一次。 |
| `RESOURCE_CANDIDATE_LIMIT` | 2 | 每名 Worker 每回合最多保留的资源目标数，限制 A* 数量，同时给 TeamPlanner 留备选。 |
| `ATTACK_TARGET_POOL_LIMIT` | 12 | 夜战目标池上限，保护 5 秒响应预算。 |
| `ATTACK_TARGET_SET_LIMIT` | 32 | 多目标攻击组合上限。 |
| `BUILD_TARGET_LOOKAHEAD` | 4 | 每回合最多检查多少个高优先级建造点。 |
| `WALL_DAY1_TARGET` | 8 | Day1 的最低墙体建设目标。 |
| `WALL_TARGET_INCREMENT_PER_DAY` | 4 | 后续每天增加多少面墙目标。 |
| `WALL_TARGET_MAX` | 20 | 墙体目标最大值，对齐官方围墙上限。 |

### 2.2 资源选择参数

资源目标预筛选与最终 ResourceApproach Reward 使用同一套参数来源，避免“Candidate 认为 A 更好、Reward 又把 B 抬上来”的双重逻辑。

当前公式为：

```text
resource_score
= resource_distance_weight / (distance + 1)
+ market_value * resource_market_value_weight
+ commitment_bonus
+ wall_stone_bonus
+ builder_role_adjustment
```

默认：

```text
resource_distance_weight       = 8.00
resource_market_value_weight   = 0.10
resource_commitment_bonus      = 3.00
resource_wall_stone_bonus      = 5.00
resource_builder_stone_bonus   = 1.00
resource_builder_nonstone_penalty = 1.00
```

因此默认策略是**距离优先、价格次要**。如果比赛后发现矿价信息的重要性明显高于路程，可以增加 `RESOURCE_MARKET_VALUE_WEIGHT`，但不需要修改 Candidate/Reward 源码。

### 2.3 Utility 倍率

最终有效权重：

```text
有效权重(component)
= StrategyProfile 基准权重(component)
× UTILITY_WEIGHT_MULTIPLIERS[component]
```

初始倍率全部为 `1.0`。Runtime Learning 当前只允许小幅调整 `economy` 倍率；其它倍率虽然可人工配置，但不会被自动学习器擅自修改。

---

## 3. 采矿行为状态

V0.5.6 不再仅凭一个 `backpack >= 80%` 判断是否返场，而是区分以下阶段。

### 3.1 白天早期：尽量填满背包

条件：

```text
day_elapsed_rounds <= EARLY_DAY_FULL_BACKPACK_ROUNDS
```

行为：

- 优先近矿；
- 即使背包超过普通高水位，也允许继续开启矿点；
- 已经贴着当前矿时优先持续 `collect`；
- 当前矿仍存在时尽量不主动换矿。

### 3.2 正常采矿：当前矿优先

Worker 一旦通过 `ResourceApproach` 承诺某个矿点，`MiningRuntimeMemory` 会记录该矿点。只要：

- 矿仍存在；
- 背包未满；
- 未触发夜前返场；

就优先继续采当前矿，避免每回合因价格/距离轻微变化在多个矿点间跳转。

### 3.3 建墙施工预留窗口

距离黑夜小于 `WALL_BUILD_RESERVE_ROUNDS` 后，如果背包中矿物比例达到 `NEAR_NIGHT_MINERAL_RETURN_RATIO`，Worker 不再继续开启远距离采矿，而是把材料带回基地。

该窗口与 prepare 不同：

- `wall_build_reserve`：经济/施工时序；
- `prepare`：更强的夜战站位阶段；
- `mining_emergency`：最后几回合的强制撤离规则。

### 3.4 最后 8 回合紧急采矿

默认：

```text
MINING_EMERGENCY_ROUNDS = 8
```

进入紧急窗口后：

- 禁止开启新矿点远征；
- 如果 Worker 已经贴着一个有效矿，本次紧急窗口允许额外 `collect` 1 次；
- `MiningRuntimeMemory` 记录该 Worker 对该矿当天是否已经使用过这次紧急采集；
- 下一回合不再继续采，转向回基地/施工/防守。

这一状态是跨回合 Memory，不通过奇偶回合等脆弱方法模拟。

---

## 4. Utility 透明化

以前日志只能看到：

```text
utility=7.42
```

现在 `UtilityBreakdown` 同时保存：

- `raw_components`：Reward 原始分量；
- `effective_weights`：StrategyProfile × Runtime multiplier 后的最终权重；
- `formula`：本次选择实际采用的完整计算式；
- `total`：最终 Utility。

总体形式：

```text
U =
  score       * w_score
+ survival    * w_survival
+ economy     * w_economy
+ information * w_information
+ position    * w_position
+ task        * w_task
- time_cost   * w_time
- opportunity * w_opportunity
- risk        * w_risk * actionRiskWeight * strategyRiskMultiplier
```

MEDIUM/HIGH 日志会显示被选动作的公式，例如：

```text
Role 10012: move -> (5,27) [resource:stone] [utility=6.31]
  UtilityFormula: U=+economy:3.20*1.60 +position:0.95*1.00 -time_cost:0.10*1.00 ...
  ResourceFormula: resource_score=8.000/(distance+1)+market_value*0.100+...
```

这使赛后调参能够回答“为什么选它”，而不是只知道“它被选了”。

---

## 5. Runtime Learning

### 5.1 设计原则

运行时学习只做**小步软调参**：

```text
Experience / Outcome
        ↓
Learner.propose()
        ↓
PolicyPatch
        ↓
Runtime allowlist + confidence gate
        ↓
单次变化夹紧
        ↓
Candidate PolicyState
        ↓
promote
```

Learner 不能直接修改 Production Policy。

### 5.2 更新频率配置

`main3.py`：

```text
RUNTIME_LEARNING_FIRST_UPDATE_ROUND = 20
RUNTIME_LEARNING_UPDATE_INTERVAL_ROUNDS = 20
```

意味着默认在第 20 回合第一次尝试，之后第 40、60、80……回合再尝试。

两者都可以修改。

### 5.3 当前允许自动更新的参数

为了避免策略漂移，自动提升有明确 allowlist：

```text
thresholds.prepare_margin_rounds
utility_weights.economy
```

其它参数可以人工配置，但不会自动学习。

### 5.4 小步保护

默认：

```text
max_relative_change = 10%
max_absolute_change = 1.0
max_patches_per_update = 1
```

例如 Learner 提议：

```text
prepare_margin_rounds: 20 -> 10
```

Runtime 不会直接接受，而是夹紧为：

```text
20 -> 19
```

避免一次比赛中的少量样本把策略整体带偏。

---

## 6. 学习更新如何进入日志

LOW / MEDIUM 都会在人类回合块中显示真正发生的更新。

LOW 示例：

```text
=====START=====
Round 40 (Day 1, DAY), Gold: 12, Score: 18
LearningUpdate: v3 utility_weights.economy 1.000->1.050
Role 10010: collect -> (9,13)
...
=====END=======
```

MEDIUM 会额外包含：

```text
LearningUpdate: v3 utility_weights.economy 1.000->1.050
  proposer=economy_utility confidence=0.71 next_update_round=60
```

HIGH 除人类块外，还保留结构化：

```text
kind=runtime_policy_updated
```

方便程序化复盘。

---

## 7. 哪些数字故意不配置/不学习

以下属于官方规则事实，保持在 `game_rules` 中：

- 白天 70、夜晚 60；
- 最大 1300 回合；
- 武器价格 25；
- Rocket/Gatling/Railgun 的攻击力、射程和冷却；
- 最多 3 座武器；
- 最多 20 面墙；
- 角色生命值/背包容量；
- 指令合法性、TaskPoint/矿区阻挡；
- 5 次异常规则。

这些数字不是“策略魔法数字”，而是环境契约。在线学习修改它们只会让 Agent 产生非法认知。

---

## 8. 新增策略参数时的规范

新增一个软参数时必须完成：

1. 在 `config/tuning.py` 中给出默认值和中文说明；
2. 在 `main3.py` 中暴露生产配置项；
3. 通过 `PolicyState.thresholds / parameters / utility_weights` 读取，而不是模块级硬编码；
4. 如果允许在线学习，加入 Runtime allowlist，并设置上下界/单步变化限制；
5. MEDIUM 日志能解释它如何影响最终 Utility 或阶段切换；
6. 增加契约测试，至少验证默认值和修改配置后的行为都发生预期变化。

原则：**能调的数字必须有名字；能学的数字必须有限制；改过的数字必须能在日志里看到。**
