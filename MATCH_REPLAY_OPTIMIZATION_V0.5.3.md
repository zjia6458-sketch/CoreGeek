# FortressAgent V0.5.3：对战复盘第一轮优化

## 1. 目标

本轮不追求一次完成 M4~M9，而是针对实战中已经被证实的高价值缺口先止血：

1. acceptTask 后必须真正进入 sandbox 任务闭环；
2. 夜晚不能连续输出空 `roleCommandMap`；
3. Worker 必须有稳定分工，避免两人一起探索或一起抢开局建造；
4. 日志必须让人一眼看到本回合状态、最终动作和 PolicyGraph 节点链。

## 2. 自进化任务闭环

新增 `src/fortress_agent/tasks/session.py::TaskSessionCoordinator`。

```text
acceptTask 成功
   ↓
phaseTask 非空
   ↓
TaskSessionCoordinator
   ├─ 首回合：find /tmp/selfEvolutionTask ...
   ├─ 每回合：task 专用 prompt
   ├─ LLM action=execute → executeCmd
   ├─ lastCmdResult → 下一回合 prompt
   └─ LLM action=submit → Pioneer submitAnswer
```

任务专用 LLM 契约为 `task-1.0`，与 StrategicAdvisory 完全隔离。活跃任务期间战略 LLM parser 不再尝试解析 task response。

任务 prompt 强制要求：
- 只依据 phaseTask、上一条 executeCmd、lastCmdResult；
- localhost 可访问，外部网络不可假设；
- 失败后最小修复而不是完全重来；
- submit 前检查所有要求字段。

确定性 fallback 目前包含：
- 首回合发现 `/tmp/selfEvolutionTask` 文件；
- 发现 `API_DOCS.md/spec.md/README.md` 后优先读取；
- 服务端明确要求 `Authorization: Bearer` 时，最小修复旧的 `X-API-Key` curl；
- `bad interpreter ^M` 时对 task sandbox 的 check 脚本做 CRLF 修复。

这些 fallback 只用于 LLM 暂时缺席，不硬编码具体比赛题答案。

## 3. 夜间 defense 止血

新增 `DefensePostCandidateGenerator`：

```text
Night
  ↓
是否已经在己方武器周围 1 格？
  ├─ 是 → AttackCandidateGenerator 可生成 attack
  └─ 否 → Multi-goal A* 前往任一合法 weapon control cell
```

若当前没有武器，则退化为基地邻域安全回撤。

同时修复一个框架错误：PolicyGraph 走到 EmergencyNode 后，`frame.viable_actions` 可能为空；旧 Runtime 又用这个空集合调用 TeamPlanner，导致 Emergency/control decision 被丢弃，最终 `{}`。V0.5.3 在团队结果为空时恢复已经通过 PolicyGraph Validate 的 control decision。

## 4. 白天提前回收

`PREPARE_MARGIN_ROUNDS = 20` 现在由 `main3.py` 显式配置。

Day 共 70 回合，因此 Day1 大约 R50 开始 prepare。BaseReturn 不再只处理 Worker，而是所有存活角色，减少 Pioneer/矿工夜晚离基地过远的问题。

## 5. 开局经济与建造分工

当前采用一个保守、确定性的 opening doctrine：

- 存活 Worker 中 ID 最小者 = primary builder；
- 前三座武器只允许 primary builder 生成 weapon build Candidate；
- 前三座武器 Rocket 有额外战略价值；
- Secondary Worker 不和 primary builder 同回合抢武器预算，有资源时也不生成 exploration Candidate，优先 resource approach / collect；
- 三座武器成形后，提高 stone 的采集/接近价值和 Wall 的建造价值。

这不是永久角色绑定：primary builder 死亡后，会自动选择当前存活 Worker 中 ID 最小者接替。

## 6. TeamPlanner 冲突后二次选择

旧行为：

```text
10011 best = MOVE(7,22)
10012 best = MOVE(7,22)
→ JointMoveCollision
→ 丢掉 10012
→ 10012 本回合空闲
```

新行为：TeamPlanner 保存每个 actor 的完整排序候选。团队约束丢掉某 actor 后，只推进该 actor 的候选索引并重新 resolve，最多 12 次。

因此上例会继续尝试：

```text
10012 second best = MOVE(9,23) toward copper
```

而不是直接挂机。

## 7. 人类可读日志

Compact 模式新增 `round_human_summary`，示例：

```text
###################################### Start ##############################################
Round 1 (Day 1, DAY), Gold: 75, Score: 0
Strategy: economy | Nodes: runtime_gate -> strategy -> candidates -> legal_filter -> rules -> rank -> validate -> finalize
  [us] worker id=10010 pos=(8,21) hp=220
  [us] pioneer id=10011 pos=(8,23) hp=200
  [us] worker id=10012 pos=(8,22) hp=220
  Role 10010: build rocket -> (8,20) [utility=...]
  Role 10011: move -> (...) [goal:task]
  Role 10012: move -> (...) [resource:...]
  ExecCmd: ...                  # 有任务命令时
  TaskStage: execute            # 有 active task 时
  DeadlineRemaining: ...s
####################################### End ############################################
```

若有 `lastCmdResult`，摘要会截取最多 800 字显示。Logger 仍然只是 human-facing projection，不参与 Memory/Policy。

## 8. 当前尚未完成的部分

V0.5.3 是第一轮优化，不代表 M4/M6/M8 已完全结束：

- TaskSession 还没有针对每种任务建立长期 SOP/Skill 归纳库；
- 任意任务答案的完整 schema 无法仅靠通用代码静态推断，目前由 task LLM 在 submit 前自查；
- Combat 仍需继续实现 Rocket AOE/Gatling cone/Railgun penetration 的更精确目标价值模拟；
- Wall 布局目前具备规则与价值偏好，但还没有完整的“缺口优先封墙/维修”布局规划器；
- 经济流水线还可继续加入背包阈值、Vendor 批量出售时机和新闻价格预测。

## 9. 验证

- 207 tests collected / 全量通过；
- Python 3.11 compatibility check PASS；
- `python main3.py <port>` HTTP smoke: 200；
- Round85 三角色远离武器时，Defense 输出回撤 MOVE，不再输出空 map；
- active task 首回合同时产生 task prompt 与 sandbox discovery executeCmd。
