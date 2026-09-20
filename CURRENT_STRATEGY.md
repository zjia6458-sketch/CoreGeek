# 当前策略检查表

更新日期：2026-09-21。本文件记录当前代码行为；历史版本文档与此冲突时，以本文件和对应回归测试为准。

## 术语与目标

本轮按“箭塔”指现有协议的 `rocket`（火箭塔）实现。协议支持的武器类型为 `rocket`、`gatling`、`railgun`，没有独立 `arrow` 类型，不能发送虚构的建筑名。

默认前期使用 3 座一级火箭塔过渡。若接管的局面已有加特林或轨道炮，它们也计入 3 座武器目标，只在空位补火箭塔，不拆掉或覆盖已有武器。当前没有自动改建为混合武器的后期规则。

## 开局与金币使用

- 默认建筑目录下，首个建设目标必须是火箭塔；武器不足 3 座时不生成建墙候选，也不购买、使用任何建筑升级券。
- 活着且 ID 按字符串排序最小的 Worker 为主建设者。白天金币至少 25、存在合法空位时，优先建火箭塔；尚未到位时优先前往武器施工位。建造动作优先于施工移动，两者均优先于普通采矿、卖矿、购物等动作，不受学习评分高低改变。
- 团队金币冲突时先支付建塔费用；主建设者正在前往武器施工位时，保留一座塔的 25 金币。其他角色只能花剩余金币，同回合卖矿收入不计入可花预算。
- 不足 25 金币时继续经济循环；夜间、没有合法空位或没有可达施工路径时，不能强行发出 build。此时采用其他合法候选。建造仍受建筑数量、占位、距离、资源和最终协议校验约束。
- 第二 Worker 开局优先采集 stone，为三塔后的三面墙建设备料。显式仅配置墙体配方的特殊地图保留独立建墙能力，不套用默认武器开局门槛。

## 武器与墙体升级

只有己方武器总数达到 3 座才开启升级计划。每回合根据真实建筑等级重新选择唯一目标；武器损失后先补数量，再恢复升级。

| 顺序 | 升级目标 | 使用道具 |
| --- | --- | --- |
| 1 | 所有武器升二级 | `WeaponUpgradeVoucher1` |
| 2 | 已有迎敌侧墙体升二级 | `WallUpgradeVoucher1` |
| 3 | 所有武器升三级 | `WeaponUpgradeVoucher2` |
| 4 | 已有迎敌侧墙体升三级 | `WallUpgradeVoucher2` |
| 5 | 基地升二级、再三级 | `StationUpgradeVoucher1/2` |
| 6 | 上下及其余墙体升二级、再三级 | `WallUpgradeVoucher1/2` |

迎敌侧识别：左上／左半图基地优先右侧墙，右下／右半图基地优先左侧墙。代码以基地 footprint 中心相对地图中心的横坐标判断，沿用游戏坐标体系，不依赖屏幕纵轴方向。迎敌侧包含该侧两个角点，其余顶部、底部墙优先级较低。

不再等待三面墙全部建完才升级已有迎敌侧墙。某阶段没有对应墙体时直接跳过；后来补建一级迎敌墙会重新进入优先升级队列。同一阶段按建筑 ID 字符串排序，避免目标漂移。

买券、持券接近目标、使用券共同读取 `next_upgrade_target()`。买不起当前目标的券时继续赚钱，不生成无意义的购券行程，也不改买低优先级墙体升级券。建筑升级顺序是确定规则；升级事务与采矿、墙体施工、维修等动作之间仍由现有收益评分选择。

## 围墙施工

三座武器后按三面墙 blueprint 施工：左侧基地建设上、下、右侧；右侧基地建设上、下、左侧，后侧保留出入口。标准 2×2 基地对应 16 格墙位。

施工顺序仍为迎敌侧中间四格→迎敌侧角点→上下交替延伸。施工导航与实际落墙共享有序目标。缺墙期间保留所需 stone；保留既有危险墙重建、维修及夜间安全导航机制。

## 本轮检查发现与修复

| 原实现 | 当前行为 |
| --- | --- |
| Rocket→Gatling→Railgun 各一座 | 空位连续补 Rocket，达到 3 座才升级 |
| 近墙且携带 stone 时可能在三塔之前建墙 | 默认建筑目录下先完成三塔 |
| 建塔靠收益加分，其他动作或角色消费可能抢占 | 排序优先建造／施工导航，并保护建塔金币 |
| 基地升级插在武器升级之间，迎敌墙排在核心全满之后 | 武器与迎敌侧墙交替升二级、三级，然后基地与其他墙 |
| 墙体升级必须等待 blueprint 完整 | 已有迎敌墙即可升级 |
| 其他墙二级先于迎敌墙三级 | 迎敌墙三级先于其他墙二级 |

## 代码与验证入口

| 关注点 | 文件／函数 |
| --- | --- |
| 开局武器类型和数量 | `src/fortress_agent/game_rules/economy.py::next_weapon_build_type` |
| 默认建造配方、成本 | `src/fortress_agent/policy/build_catalog.py` |
| 建塔与墙体候选 | `src/fortress_agent/candidates/business.py::BuildCandidateGenerator` |
| 主建设者返场 | `src/fortress_agent/candidates/navigation.py::WeaponBuildApproachCandidateGenerator` |
| 开局动作排序 | `src/fortress_agent/policy/construction_priority.py`、`ranker.py` |
| 金币保护 | `src/fortress_agent/policy/team_constraints.py::GoldBudgetConstraint` |
| 基地方向、墙位 | `src/fortress_agent/game_rules/build_area.py` |
| 升级顺序 | `src/fortress_agent/game_rules/upgrades.py::next_upgrade_target` |
| 顺序、数量、方向、金币回归 | `tests/unit/test_v059_strategy_repairs.py` |
| 最终 build/use 指令回归 | `tests/integration/test_strategy_economy_prepare_defense.py` |

快速检查命令（Python 3.11，安装开发测试依赖后）：

```powershell
python -m pytest tests/unit/test_v059_strategy_repairs.py tests/integration/test_strategy_economy_prepare_defense.py tests/integration/test_configured_build_recipe.py
```

本轮验证：Python 3.11.14 下全量测试 **271 passed**；新增模块及核心升级、排序、回归测试文件的 Ruff 检查通过，`git diff --check` 通过。验证包括生产 Runtime 输出的真实协议格式，但未进行在线比赛验证。本机原 `.venv` 的解释器路径失效，本轮使用工作区 `tmp/` 下的隔离 Python 环境运行测试。

实战查看日志时，核对主建设者的 `build rocket`、`weapon_build`、升级券 `buy/use`，以及每次 `lastCmdResult`。候选或发出指令只表示计划／尝试，建造与升级成功必须以下一回合服务器状态和反馈为准。
