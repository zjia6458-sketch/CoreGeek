# FortressAgent V0.5.4：对战复盘第二轮深挖

## 1. 本轮目标

V0.5.3 已经解决“接任务后完全不执行”“夜晚连续空响应”“Worker 同时抢建塔”等第一层问题。V0.5.4 不再以增加动作种类为目标，而是把已经存在的能力串成可持续闭环：Pioneer 做任务时 Worker 仍然生产；武器不仅能开火，还按正式弹道/AOE 规则估值；矿工采到资源以后能够决定继续采、去卖还是回基地施工；建设阶段从前三座 Rocket 平滑切换到外圈围墙。

## 2. M8：自进化任务从单次闭环升级为可积累 SOP

### 2.1 TaskPoint Anchor

`phaseTask` 非空时，Pioneer 被视为处于任务会话。根据当前 Pioneer 邻接的己方 TaskPoint 分组解析 `active_task_anchor_positions()`。普通 Move/Explore 不再为 Pioneer 生成；Legal 和 FinalValidator 也只允许继续停留在“当前任务点”邻域，而不是任意己方任务点。

这满足官方规则：领取任务后离开任务点周围一格会直接导致任务结束。

### 2.2 任务剩余回合

TaskSession 会根据同 TaskPoint 的 `PlayerTask.timeoutRounds` 和 session 起始回合估算 `remaining_rounds`，写入任务 prompt 与人类日志。剩余回合少时，LLM 被明确要求优先整理并提交已有最可信答案，而不是继续低价值探索。

### 2.3 旧任务 LLM 响应隔离

`TaskLLMAdvice.source_round` 现在真正参与校验。若响应早于当前 `session.started_round`，视为上一任务残留，不执行其中的 `execute_cmd` 或 `task_answer`。

### 2.4 文件发现顺序

首条 deterministic 命令仍然只做 sandbox 文件发现。发现文件后优先读取具体 `task*.md/txt`，再读取 `API_DOCS.md/spec.md/README.md`。如果任务正文只出现相对文档名，则使用 `find` 定位真实路径，避免假设当前工作目录。

### 2.5 TaskSkillMemory

同一任务族按 `task_type + TaskPoint terrain type` 建立 family key。任务结束后，如果分数或金币出现正向收益，保存本 Agent 实际发送过的成功命令轨迹。下一次同类任务开始时，把最近成功命令作为 SOP 参考放入 prompt。

重要边界：SOP **只作为 LLM 参考，不自动重放**。文件路径、城市、API 参数、token 都可能改变，机械重放风险过高。

### 2.6 Task 与 Worker 经济并行

`active_task` StrategyProfile 现在同时开放 `gather/sell/buy/build`。角色职责由 Candidate 类型自然分离：Pioneer 留在 TaskPoint 运行 TaskSession；两个 Worker 继续采矿、建塔、卖矿和建墙。任务不再冻结全队经济。

## 3. M6：三种武器统一进入 Combat Rules

新增 `game_rules/combat.py`。Candidate 与 Reward 共享同一伤害估计，避免“候选认为好、Reward 用另一套规则评分”。

### 3.1 Rocket

落点候选不再局限于机器人脚下，而是包含机器人格及其 8 邻域。按中心 20、周围 8 格 10 伤害计算，允许多枚导弹伤害叠加，并综合击杀积分与对基地威胁选择落点。

因此机器人簇周围的空格也可能成为最优 `targetPos`。

### 3.2 Gatling

依据“坐标中心连线”的正式规则，用整数叉积判断机器人是否位于弹道线段上。每颗子弹命中该弹道上距离武器最近的存活机器人，造成 10 点伤害。多目标仍需满足任意两目标方向夹角不超过 90°。

### 3.3 Railgun

同样根据中心连线找出路径机器人，并按距离从近到远处理。能量为 level1/2/3 = 10/20/30；每个机器人受到 `min(剩余能量, 当前剩余HP)`，然后扣减能量直到耗尽或到达终点。

### 3.4 Controller 站位

Prepare/Night 不再让三个角色都追“所有武器控制格的并集”。最多 3 个角色与最多 3 座武器做小规模确定性匹配，目标是最小化站位距离；已经在某武器周围的角色会获得留位优势，Rocket 略有优先。白天准备阶段提前进入这些控制位，夜晚沿用。

## 4. M4：经济流水线

### 4.1 Worker 职责

最低 ID 存活 Worker 继续作为主建设者。另一 Worker 主要承担现金矿物流。

### 4.2 矿点候选收敛

ResourceApproach 不再为每个 Worker 对全图所有矿跑路径。每回合根据距离、当前价格和建设阶段评分，每个 Worker 最多保留两个矿点，既减少 A* 开销，也降低频繁换矿。

三座武器完成且墙未满时，主建设者对 stone 获得强偏好；另一个矿工继续偏向高价值矿物。

### 4.3 满载切换

背包使用率达到 80% 后停止继续生成 ResourceApproach，让 VendorApproach/Sell 有机会接管。

### 4.4 Stone 战略保留

前三座武器未完成前，stone 仍可正常出售换取现金。三塔完成以后、20 面墙未完成之前，背包中的 stone 默认作为墙体材料保留，普通 Sell 不再出售这部分库存。

## 5. M5：施工返场

### 5.1 WeaponBuildApproach

当武器数 `< 3` 且金币 `>=25` 时，如果主建设者离开武器圈，会主动返回下一座推荐武器格的施工位置。前三座武器仍然优先 Rocket。

### 5.2 WallBuildApproach

当三塔完成、墙数 `<20` 且 Worker 携带 stone 时，主动返回外圈墙体施工位置。不会再出现“采完石头后继续在矿区探索，只有偶然回基地才建墙”。

### 5.3 建造位置顺序

Weapon ring 与 Wall ring 都保持正式 0/1/2 合法性不变；新增的 `ordered_*_build_cells` 只是策略排序。默认优先建设更靠地图内部的一侧，这是一条可替换启发式，不是官方硬规则。

## 6. Explore 候选收紧

Worker 在以下情况不再生成普通 exploration：

- 地图仍有可用矿；
- 主建设者还有前三座武器要建且金币足够；
- 三塔完成后携带 stone 且外墙未完成；
- 背包使用率达到 80%。

这避免 information utility 把生产链反复打断。Pioneer 在非任务状态仍保留探索职责。

## 7. 人类日志增强

Compact 人类摘要继续保持单 logger，同时增加：

- Worker 人类职责：`主建设者 / 矿工 / 开拓者`；
- `LastCmdResult` 预览；
- TaskStage 的 `remaining` 与 `anchor`；
- Node chain 与最终 action utility。

日志仍然只是 projection：Memory/Experience/策略不读取日志。

## 8. 已验证实战回放

基于用户提供的 R10 状态回放，单回合同步得到：

- `10010 build rocket`；
- `10012 move -> copper`；
- Pioneer 不移动；
- 顶层 `executeCmd=find /tmp/selfEvolutionTask ...`；
- task prompt 正常发送。

基于夜间机器人簇回放，Rocket 最终选择一个无机器人的中心落点 `(15,15)`，同时覆盖四个低血机器人，FinalValidator 正常放行。

## 9. 当前仍未完成的部分

V0.5.4 仍不是全部 M4/M6/M8/M9：

- Task 最终答案 schema 仍依赖任务说明 + LLM，自定义字段的通用结构校验尚未实现；
- TaskSkillMemory 当前仅存在于单场 Runtime 内，没有跨进程持久化；
- Gatling/Railgun 的中心连线模型依据正式文字规则实现，如果判题器内部使用不同离散光栅算法，需要用真实反馈继续校准；
- 墙体“朝地图内部优先”是策略启发式，后续应结合机器人历史进攻方向动态学习；
- 宝藏长期传闻、采购策略、Bomb/Dizzy、升级券时机仍属于后续 M7/M9；
- 对敌方玩家的主动攻击/博弈尚未作为主要目标优化。

## 10. 下一轮建议指标

下一局重点统计：

1. active task 期间 Worker 的 `collect/build/sell` 是否持续出现；
2. 单任务 `executeCmd` 数、任务完成耗时、`submitAnswer` 次数与得分；
3. 夜间每座武器的 attack 次数与 controller 覆盖率；
4. Rocket 单次命中的机器人数量；
5. 三塔完成回合、第一面墙/第十面墙/第二十面墙完成回合；
6. Worker 的 move:collect 比例以及背包达到高水位后到首次 sell 的回合差。
