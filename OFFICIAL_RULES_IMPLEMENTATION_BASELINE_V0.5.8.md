# FortressAgent V0.5.8 实现基线

## FROZEN：官方硬规则

- 8 方向移动，Chebyshev 距离；
- 2×2 Station footprint；
- distance=1 为武器建造区，distance=2 为围墙建造区；
- 三种武器全局同时最多 3 座；
- Worker 白天可建造；Worker 可按当前比赛规则在夜间安全采矿；
- 机器人全局可见，攻击距离来自协议/规则；
- Pioneer 控制武器必须位于武器 Chebyshev 1；一个角色同一回合只控制一座武器。

官方规则不可被 Runtime Learning 修改。

## IMPLEMENTED：V0.5.8 战略 Doctrine

- 三 Rocket 共享单一固定 controller；
- 左侧/左上基地三面墙：TOP/BOTTOM/RIGHT；
- 右侧/右下基地三面墙：TOP/BOTTOM/LEFT；
- 标准 Blueprint 共 16 个墙位，16/16 才视为主动建设完成；
- 迎敌侧优先施工，上下墙从迎敌侧向后方交替推进；
- 夜间 `RobotTrajectoryMemory + RobotThreatField + SafePathPlanner`；
- 威胁预测同时覆盖 Station 最快线和最近真实 heading；
- 夜间矿点需验证去程、驻留窗口与撤离路线；
- 资源目标 commitment 防止 A/B 矿点振荡；危险变化可立即解除 commitment。

## NEXT

- 更精确的墙体 breach-time 机器人推进模拟；
- 多机器人围堵/交汇风险模型；
- 夜间 Safe A* 的显式 WAIT 时间节点；
- 基于实战轨迹统计自动调节安全 margin（仍只能作为 Learned Overlay 软参数）。
