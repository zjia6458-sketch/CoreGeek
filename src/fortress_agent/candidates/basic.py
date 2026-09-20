from __future__ import annotations

from fortress_agent.domain.action import (
    AttackAction,
    ExploreAction,
    GatherAction,
    MoveAction,
    ResourceApproachAction,
)
from fortress_agent.memory.resources import ResourceStatus
from fortress_agent.game_rules.geometry import chebyshev_distance, is_adjacent8, neighbors8, angle_within_90
from fortress_agent.game_rules.catalog import weapon_attack_range
from fortress_agent.game_rules.combat import best_rocket_targets, estimate_attack_value
from fortress_agent.game_rules.economy import (
    primary_builder_id, weapon_count, wall_count, backpack_usage_ratio, inventory_counts,
    wall_construction_due, stone_batch_target, wall_return_urgent,
    backpack_high_watermark_reached, in_mining_emergency_window,
    is_early_day_full_mining, near_night_mineral_return_due,
    resource_selection_score, should_hold_current_mine,
)
from fortress_agent.game_rules.night_safety import (
    night_resource_route, night_gather_is_safe, night_retreat_step,
)
from itertools import combinations
from fortress_agent.domain.state import Position
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.strategy import StrategyProfile
from fortress_agent.world.pathfinding import AStarPathfinder, NavigationPolicy
from fortress_agent.world.traversability import TraversabilityMap

from .base import CandidateGenerator


def _neighbors(x: int, y: int):
    return neighbors8(x, y)


def _inside(ctx: PolicyContext, x: int, y: int) -> bool:
    return (
        0 <= x < ctx.state.map_width
        and 0 <= y < ctx.state.map_height
    )


class MoveCandidateGenerator(CandidateGenerator):
    generator_id = "move"
    tags = frozenset({"move", "prepare", "defense"})

    def generate(
        self,
        ctx: PolicyContext,
        strategy: StrategyProfile,
    ):
        # 夜间不使用普通随机 MOVE：Pioneer 由 DefensePost 控制，Worker 由
        # NightResourceApproach / NightWorkerRetreat 使用 Safe A* 控制。
        if ctx.state.phase.lower() == "night":
            return ()
        actions = []
        traversability = TraversabilityMap.from_state_and_memory(
                ctx.state,
                ctx.world_memory,
                ctx.feedback_memory,
            )

        for actor in ctx.state.characters:
            if actor.role.lower() == "pioneer" and ctx.state.phase_task.strip():
                continue
            # Worker 已经贴着一个仍可采的矿时，正常阶段优先原地 collect，
            # 不生成随机 MOVE 去打断矿点连续采集。紧急撤离/返场窗口会让该条件自动失效。
            if actor.role.lower() == "worker" and should_hold_current_mine(ctx, actor):
                continue
            for x, y in _neighbors(actor.position.x, actor.position.y):
                if not _inside(ctx, x, y):
                    continue

                if not traversability.is_walkable(x, y):
                    continue

                cell = ctx.world_memory.cell(x, y)
                if cell.terrain is not None and cell.terrain.lower() == "wall":
                    continue

                actions.append(
                    MoveAction(
                        actor_id=actor.actor_id,
                        action_type="move",
                        x=x,
                        y=y,
                    )
                )

        return tuple(actions)


class ExplorationCandidateGenerator(CandidateGenerator):
    generator_id = "exploration"
    tags = frozenset({"explore"})

    def generate(
        self,
        ctx: PolicyContext,
        strategy: StrategyProfile,
    ):
        actions = []
        traversability = TraversabilityMap.from_state_and_memory(
                ctx.state,
                ctx.world_memory,
                ctx.feedback_memory,
            )

        available_resource_exists = any(
            resource.status is ResourceStatus.AVAILABLE
            for resource in ctx.world_memory.available_resources()
        )

        for actor in ctx.state.characters:
            if actor.role.lower() == "pioneer" and ctx.state.phase_task.strip():
                continue
            # Worker 的核心职责是经济与建设。有可采资源时继续给 Worker 生成
            # exploration 会让高 information utility 抢走 gather/resource_approach，
            # 形成“满图乱走但产量很低”。Pioneer 仍保留探索职责。
            if actor.role.lower() == "worker":
                builder_id = primary_builder_id(ctx.state)
                construction_due = (
                    (weapon_count(ctx.state) < 3 and str(actor.actor_id) == builder_id and ctx.state.gold_self >= 25)
                    or (weapon_count(ctx.state) >= 3 and wall_count(ctx.state) < 20 and inventory_counts(actor)["stone"] > 0)
                )
                if available_resource_exists or construction_due or backpack_high_watermark_reached(actor, ctx.policy_state):
                    continue
            for x, y in _neighbors(actor.position.x, actor.position.y):
                if not _inside(ctx, x, y):
                    continue

                if not traversability.is_walkable(x, y):
                    continue

                cell = ctx.world_memory.cell(x, y)
                if cell.terrain is not None and cell.terrain.lower() == "wall":
                    continue

                actions.append(
                    ExploreAction(
                        actor_id=actor.actor_id,
                        action_type="move",
                        x=x,
                        y=y,
                    )
                )

        return tuple(actions)


class GatherCandidateGenerator(CandidateGenerator):
    generator_id = "gather"
    # prepare_gather 只允许“已经在矿旁”的 collect；ResourceApproach 仍只有 gather 标签，
    # 因而 prepare 阶段不会再远距离追矿。
    tags = frozenset({"gather", "prepare_gather", "defense"})

    def generate(
        self,
        ctx: PolicyContext,
        strategy: StrategyProfile,
    ):
        actions = []
        workers = [
            actor for actor in ctx.state.characters
            if actor.role.lower() == "worker"
        ]

        for actor in workers:
            # 背包已满时 collect 一定没有收益。
            if actor.backpack_capacity and sum(i.amount for i in actor.inventory) >= actor.backpack_capacity:
                continue

            for resource in ctx.world_memory.available_resources():
                if resource.status is not ResourceStatus.AVAILABLE:
                    continue
                if not is_adjacent8(actor.position, (resource.x, resource.y)):
                    continue

                # 距离黑夜进入紧急窗口后，只允许在“刚进入紧急状态且已经站在矿旁”
                # 时额外 collect 一次；MiningRuntimeMemory 会记录这一次，下一回合
                # 同一 Worker/矿点不再生成 gather，强制交给返场/prepare。
                if in_mining_emergency_window(ctx.state, ctx.policy_state):
                    if (
                        ctx.mining_memory is not None
                        and ctx.mining_memory.emergency_sample_taken(
                            actor.actor_id,
                            day=ctx.state.day,
                            resource_id=resource.resource_id,
                        )
                    ):
                        continue
                # 建墙预留窗口与紧急窗口不同：当背包中的矿物已经达到配置比例，
                # 即使矿还没采完也应该返场，把已有材料转换成围墙/现金。
                elif near_night_mineral_return_due(ctx.state, actor, ctx.policy_state):
                    continue

                # 夜间 collect 必须重新通过“停留一回合 + 下一回合可撤离”的
                # 安全检查；高价值资源不能覆盖生存硬约束。
                if ctx.state.phase.lower() == "night" and not night_gather_is_safe(ctx, actor, resource):
                    continue

                # 其余阶段尽量把当前矿采完。即使 stone 已达到正常批量目标，只要
                # Worker 已经站在该矿旁，仍继续 collect，直到矿消失、背包满或进入
                # 上面的夜前返场条件。
                actions.append(
                    GatherAction(
                        actor_id=actor.actor_id,
                        action_type="gather",
                        resource_id=resource.resource_id,
                    )
                )

        return tuple(actions)

class ResourceApproachCandidateGenerator(CandidateGenerator):
    """让 Worker 前往资源周围的可通行交互格。

    目标预筛选公式完全参数化：默认距离权重大于售价权重，因此优先就近采矿；
    当前已经承诺的矿点获得黏性奖励，减少每回合切换目标。
    """

    generator_id = "resource_approach"
    tags = frozenset({"gather"})

    def generate(self, ctx: PolicyContext, strategy: StrategyProfile):
        if ctx.state.phase.lower() != "day":
            return ()

        traversability = TraversabilityMap.from_state_and_memory(
            ctx.state, ctx.world_memory, ctx.feedback_memory
        )
        pathfinder = AStarPathfinder(width=ctx.state.map_width, height=ctx.state.map_height)
        actions = []
        workers = tuple(actor for actor in ctx.state.characters if actor.role.lower() == "worker")
        wall_due = wall_construction_due(ctx.state, ctx.policy_state)
        stone_available = any(
            r.status is ResourceStatus.AVAILABLE and r.resource_type.lower() == "stone"
            for r in ctx.world_memory.available_resources()
        )
        candidate_limit = max(1, int(ctx.policy_state.thresholds.get("resource_candidate_limit", 2.0)))

        builder_id = primary_builder_id(ctx.state)
        for actor in workers:
            # Worker-1 在三 Rocket 完成前保持主建设职责；只要仍有足够金币建下一座，
            # 不启动采矿远征。Worker-2 开局若存在 stone，则只选择最近 stone。
            if weapon_count(ctx.state) < 3 and str(actor.actor_id) == builder_id and ctx.state.gold_self >= 25:
                continue
            used = sum(i.amount for i in actor.inventory)
            capacity = actor.backpack_capacity or 0
            early_fill = is_early_day_full_mining(ctx.state, ctx.policy_state)

            # 紧急窗口不再启动任何新远征。
            if in_mining_emergency_window(ctx.state, ctx.policy_state):
                continue
            # 夜前施工预留窗口内，背包矿物达到阈值就返场。
            if near_night_mineral_return_due(ctx.state, actor, ctx.policy_state):
                continue
            # 白天早期希望尽量填满整个背包，因此高水位阈值此时不生效；
            # 非早期阶段则达到高水位后停止追新矿。
            if capacity and used >= capacity:
                continue
            if not early_fill and backpack_high_watermark_reached(actor, ctx.policy_state):
                continue

            inventory = inventory_counts(actor)
            batch_target = stone_batch_target(ctx.state, actor, ctx.policy_state)
            # 当前不在矿旁时，达到 stone 运输批量即可返场；但白天早期继续填包。
            if wall_due and not early_fill and inventory["stone"] >= batch_target > 0:
                continue

            min_commit = max(0, int(ctx.policy_state.thresholds.get("resource_commitment_min_rounds", 4.0)))
            committed = (
                ctx.mining_memory.committed_resource(actor.actor_id)
                if ctx.mining_memory is not None
                and ctx.mining_memory.commitment_active(
                    actor.actor_id, current_round=ctx.state.round_id, min_rounds=min_commit
                )
                else None
            )
            candidates = []
            for resource in ctx.world_memory.available_resources():
                if committed is not None and str(resource.resource_id) != committed:
                    continue
                if resource.status is not ResourceStatus.AVAILABLE:
                    continue
                distance = chebyshev_distance(actor.position, (resource.x, resource.y))
                if distance == 1:
                    # 已在矿旁由 GatherCandidate 接管。
                    continue

                # 第二个 Worker 开局立即承担采石职责；三塔完成后两个 Worker 都
                # 只开新的 stone 行程直到三面墙 Blueprint 完成。已经贴着的当前矿
                # 仍由 GatherCandidate 采完，避免半途来回切换。
                if weapon_count(ctx.state) < 3 and str(actor.actor_id) != builder_id and stone_available and resource.resource_type.lower() != "stone":
                    continue
                if wall_due and stone_available and resource.resource_type.lower() != "stone":
                    continue

                score, components, formula = resource_selection_score(
                    ctx, actor, resource, distance=distance
                )
                candidates.append((score, -distance, str(resource.resource_id), resource, components, formula))

            for _, _, _, resource, _components, _formula in sorted(candidates, reverse=True)[:candidate_limit]:
                access_cells = traversability.resource_access_cells(resource)
                if not access_cells:
                    continue
                result = pathfinder.find_path_to_any(
                    ctx.world_memory,
                    actor.position,
                    access_cells,
                    policy=NavigationPolicy.ALLOW_UNKNOWN,
                    traversability=traversability,
                    deadline=ctx.deadline,
                )
                if not result.found or result.steps < 1:
                    continue
                step = result.path[1]
                actions.append(
                    ResourceApproachAction(
                        actor_id=actor.actor_id,
                        action_type="move",
                        x=step.x,
                        y=step.y,
                        resource_id=resource.resource_id,
                    )
                )

        return tuple(actions)


class NightResourceApproachCandidateGenerator(CandidateGenerator):
    """夜间 Worker 只对通过完整安全门控的边缘矿生成移动候选。"""

    generator_id = "night_resource_approach"
    tags = frozenset({"defense"})

    def generate(self, ctx: PolicyContext, strategy: StrategyProfile):
        if ctx.state.phase.lower() != "night":
            return ()
        actions = []
        candidate_limit = max(1, int(ctx.policy_state.thresholds.get("resource_candidate_limit", 2.0)))
        for actor in ctx.state.characters:
            if actor.role.lower() != "worker" or actor.hp <= 0:
                continue
            capacity = actor.backpack_capacity or 0
            used = sum(i.amount for i in actor.inventory)
            if capacity and used >= capacity:
                continue
            min_commit = max(0, int(ctx.policy_state.thresholds.get("resource_commitment_min_rounds", 4.0)))
            committed_id = (
                ctx.mining_memory.committed_resource(actor.actor_id)
                if ctx.mining_memory is not None
                and ctx.mining_memory.commitment_active(
                    actor.actor_id, current_round=ctx.state.round_id, min_rounds=min_commit
                )
                else None
            )
            committed_safe = False
            if committed_id is not None:
                current = next((
                    r for r in ctx.world_memory.available_resources()
                    if str(r.resource_id) == committed_id
                ), None)
                committed_safe = current is not None and night_resource_route(ctx, actor, current) is not None

            candidates = []
            for resource in ctx.world_memory.available_resources():
                # Keep the same mine while its route remains safe. Safety has
                # higher priority and immediately releases this filter.
                if committed_safe and str(resource.resource_id) != committed_id:
                    continue
                if resource.status is not ResourceStatus.AVAILABLE:
                    continue
                if is_adjacent8(actor.position, (resource.x, resource.y)):
                    # GatherCandidate handles the stationary action.
                    continue
                route = night_resource_route(ctx, actor, resource)
                if route is None or route.path.steps < 1:
                    continue
                distance = route.path.steps
                market = float(ctx.state.market_prices.get(resource.resource_type, 1.0))
                w_safety = float(ctx.policy_state.parameters.get("night_resource_safety_weight", 10.0))
                w_distance = float(ctx.policy_state.parameters.get("night_resource_distance_weight", 7.0))
                w_value = float(ctx.policy_state.parameters.get("night_resource_value_weight", 0.08))
                score = route.safety_score * w_safety + w_distance / (distance + 1.0) + market * w_value
                candidates.append((score, -distance, str(resource.resource_id), resource, route))
            for _, _, _, resource, route in sorted(candidates, reverse=True)[:candidate_limit]:
                step = route.path.path[1]
                actions.append(ResourceApproachAction(
                    actor_id=actor.actor_id,
                    action_type="move",
                    x=step.x,
                    y=step.y,
                    resource_id=resource.resource_id,
                ))
        return tuple(actions)


class NightWorkerRetreatCandidateGenerator(CandidateGenerator):
    """机器人逼近或没有安全矿时，Worker 沿 Safe A* 退往低风险边缘。"""

    generator_id = "night_worker_retreat"
    tags = frozenset({"defense"})

    def generate(self, ctx: PolicyContext, strategy: StrategyProfile):
        if ctx.state.phase.lower() != "night":
            return ()
        actions = []
        for actor in ctx.state.characters:
            if actor.role.lower() != "worker" or actor.hp <= 0:
                continue
            step = night_retreat_step(ctx, actor)
            if step is None or step == actor.position:
                continue
            actions.append(MoveAction(
                actor_id=actor.actor_id,
                action_type="move",
                x=step.x,
                y=step.y,
            ))
        return tuple(actions)


class AttackCandidateGenerator(CandidateGenerator):
    """夜间武器攻击候选生成器。

    为避免机器人数量增大后 Gatling 组合数呈组合爆炸，只从排序后的高价值
    目标池中组合，并限制单武器候选集合数量。最终几何合法性仍由 Legal/
    FinalValidator 再次校验，因此这里的裁剪只影响搜索宽度，不影响安全性。
    """

    generator_id = "attack"
    tags = frozenset({"defense"})
    def generate(self, ctx: PolicyContext, strategy: StrategyProfile):
        if ctx.state.phase.lower() != "night":
            return ()
        actions = []
        for weapon in ctx.state.buildings:
            if weapon.owner != "self" or weapon.building_type not in {"gatling", "railgun", "rocket"}:
                continue
            if weapon.building_type == "rocket" and weapon.cooldown_remaining > 0:
                continue

            # V0.5.8 doctrine: Pioneer is the dedicated night weapon controller.
            # Workers remain free for safe edge mining/retreat and never steal the
            # controller slot from Pioneer.
            living_pioneers = tuple(
                actor for actor in ctx.state.characters
                if actor.role.lower() == "pioneer" and actor.hp > 0
            )
            preferred = tuple(
                actor for actor in living_pioneers
                if is_adjacent8(actor.position, weapon.position)
            )
            # Doctrine prefers Pioneer. If Pioneer is dead/absent, allowing a
            # Worker fallback is safer than leaving a ready weapon unused.
            controllers = preferred if living_pioneers else tuple(
                actor for actor in ctx.state.characters
                if actor.hp > 0 and is_adjacent8(actor.position, weapon.position)
            )
            if not controllers:
                continue

            targets = [
                enemy for enemy in ctx.state.enemies
                if enemy.hp > 0 and self._in_range(ctx, weapon, enemy.position)
            ]
            targets.sort(key=lambda enemy: (
                -float(enemy.attack or 0) / (chebyshev_distance(enemy.position, weapon.position) + 1),
                -float(enemy.score_value or 0), enemy.hp, str(enemy.enemy_id),
            ))
            max_target_pool = max(1, int(ctx.policy_state.thresholds.get("attack_target_pool_limit", 12.0)))
            max_target_sets = max(1, int(ctx.policy_state.thresholds.get("attack_target_set_limit", 32.0)))
            targets = targets[:max_target_pool]

            required = 1 if weapon.building_type == "railgun" else max(1, int(weapon.level or 1))
            # Rocket 的 targetPos 是导弹落点，不要求每个落点都有机器人；升级后即使
            # 只有一个敌人，也可以用多个互异落点叠加中心/溅射伤害。Gatling 则仍
            # 要求有足够的实际目标来组成合法 90° 锥形。
            if weapon.building_type != "rocket" and len(targets) < required:
                continue
            if weapon.building_type == "rocket" and not targets:
                continue

            if weapon.building_type == "railgun":
                target_sets = [tuple(Position(enemy.position.x, enemy.position.y) for enemy in (target,)) for target in targets[: max_target_sets]]
            elif weapon.building_type == "gatling":
                scored_sets = []
                for combo in combinations(targets, required):
                    if not self._gatling_cone_ok(weapon.position, combo):
                        continue
                    points = tuple(Position(enemy.position.x, enemy.position.y) for enemy in combo)
                    score, survival = estimate_attack_value(ctx.state, weapon, points)
                    scored_sets.append((score * 8.0 + survival, points))
                scored_sets.sort(key=lambda item: (-item[0], tuple((p.x, p.y) for p in item[1])))
                target_sets = [points for _, points in scored_sets[: max_target_sets]]
            else:
                optimized = best_rocket_targets(ctx.state, weapon, target_count=required)
                target_sets = [optimized] if len(optimized) == required else []

            for controller in controllers:
                for selected_targets in target_sets:
                    actions.append(AttackAction(
                        actor_id=weapon.building_id,
                        action_type="attack",
                        controller_id=controller.actor_id,
                        targets=tuple(selected_targets),
                    ))
        return tuple(actions)

    @staticmethod
    def _gatling_cone_ok(origin: Position, enemies) -> bool:
        positions = [enemy.position for enemy in enemies]
        return all(angle_within_90(origin, a, b) for a, b in combinations(positions, 2))

    @staticmethod
    def _in_range(ctx: PolicyContext, weapon, target: Position) -> bool:
        if weapon.building_type == "rocket" and int(weapon.level or 1) >= 3:
            return 0 <= target.x < ctx.state.map_width and 0 <= target.y < ctx.state.map_height
        server_range = int(weapon.attack_range or 0)
        official_range = weapon_attack_range(weapon.building_type, weapon.level)
        if official_range is None:
            return True
        effective = int(official_range) if server_range <= 0 else min(server_range, int(official_range))
        return chebyshev_distance(weapon.position, target) <= effective
