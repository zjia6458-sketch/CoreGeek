from __future__ import annotations

from collections import Counter
from itertools import permutations

from fortress_agent.domain.action import GoalApproachAction
from fortress_agent.domain.state import Position
from fortress_agent.game_rules.geometry import chebyshev_distance, is_adjacent8
from fortress_agent.game_rules.economy import (
    sellable_amount, weapon_count, primary_builder_id,
    wall_construction_due, stone_batch_target,
    near_night_mineral_return_due, in_mining_emergency_window,
    wall_fixer_target, wall_rebuild_target,
)
from fortress_agent.game_rules.tasks import task_zone_positions_for_task
from fortress_agent.game_rules.catalog import KNOWN_WEAPON_SHOP_PRICES
from fortress_agent.game_rules.upgrades import next_upgrade_target
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.strategy import StrategyProfile
from fortress_agent.world.occupancy import BuildingFootprintResolver
from fortress_agent.game_rules.build_area import (
    ordered_wall_build_cells, rocket_cluster_plan,
    wall_blueprint_missing_count, wall_blueprint_complete,
)
from fortress_agent.world.pathfinding import AStarPathfinder, NavigationPolicy
from fortress_agent.world.safe_pathfinding import SafePathPlanner
from fortress_agent.game_rules.night_safety import threat_field
from fortress_agent.world.traversability import TraversabilityMap

from .base import CandidateGenerator


def _path_step(ctx, actor, goals):
    traversability = TraversabilityMap.from_state_and_memory(
        ctx.state,
        ctx.world_memory,
        ctx.feedback_memory,
    )
    valid_goals = tuple(
        goal for goal in goals
        if traversability.is_walkable(goal.x, goal.y)
    )
    if not valid_goals:
        return None
    path = AStarPathfinder(
        width=ctx.state.map_width,
        height=ctx.state.map_height,
    ).find_path_to_any(
        ctx.world_memory,
        actor.position,
        valid_goals,
        policy=NavigationPolicy.ALLOW_UNKNOWN,
        traversability=traversability,
        deadline=ctx.deadline,
    )
    if not path.found or path.steps < 1:
        return None
    return path.path[1]


def _safe_path_step(ctx, actor, goals):
    """Night-only Safe A* step using predicted robot threat by ETA."""
    traversability = TraversabilityMap.from_state_and_memory(
        ctx.state, ctx.world_memory, ctx.feedback_memory
    )
    valid_goals = tuple(goal for goal in goals if traversability.is_walkable(goal.x, goal.y))
    if not valid_goals:
        return None
    planner = SafePathPlanner(
        width=ctx.state.map_width,
        height=ctx.state.map_height,
        threat=threat_field(ctx),
        threat_weight=float(ctx.policy_state.parameters.get("night_threat_path_weight", 6.0)),
        hard_risk_threshold=float(ctx.policy_state.parameters.get("night_hard_risk_threshold", 1.0)),
        max_steps=int(ctx.policy_state.thresholds.get("night_safe_path_max_steps", 64.0)),
    )
    path = planner.find_path_to_any(
        ctx.world_memory, actor.position, valid_goals,
        traversability=traversability, policy=NavigationPolicy.ALLOW_UNKNOWN,
        deadline=ctx.deadline,
    )
    if not path.found or path.steps < 1:
        return None
    return path.path[1]


def _defense_weapon_assignment(ctx, actors, weapons, traversability):
    """对最多 3 个角色/3 座武器做确定性最小距离匹配。"""
    actors = tuple(sorted((a for a in actors if a.hp > 0), key=lambda a: str(a.actor_id)))
    weapons = tuple(sorted(weapons, key=lambda w: ({"rocket": 0, "railgun": 1, "gatling": 2}.get(w.building_type, 9), str(w.building_id))))
    if not actors or not weapons:
        return {}
    n = min(len(actors), len(weapons))
    best = None
    best_cost = float("inf")
    for chosen in permutations(weapons, n):
        cost = 0.0
        mapping = {}
        for actor, weapon in zip(actors[:n], chosen):
            access = traversability.interaction_access_cells(weapon.position)
            if not access:
                cost += 9999.0
                continue
            distance = min(chebyshev_distance(actor.position, cell) for cell in access)
            # 已经在控制位的角色尽量不换炮；Rocket 略优先。
            if is_adjacent8(actor.position, weapon.position):
                distance -= 2.0
            if weapon.building_type == "rocket":
                distance -= 0.25
            cost += distance
            mapping[str(actor.actor_id)] = weapon
        key = tuple(str(mapping.get(str(a.actor_id), "")) for a in actors[:n])
        candidate = (cost, key, mapping)
        if cost < best_cost or (cost == best_cost and (best is None or key < best[1])):
            best_cost = cost
            best = candidate
    return {} if best is None else best[2]


def _inventory(actor) -> Counter[str]:
    return Counter({item.item_type.lower(): item.amount for item in actor.inventory})


class TaskApproachCandidateGenerator(CandidateGenerator):
    generator_id = "task_approach"
    tags = frozenset({"task", "defense"})

    def generate(self, ctx: PolicyContext, strategy: StrategyProfile):
        if ctx.state.phase not in {"day", "night"} or ctx.state.phase_task.strip():
            return ()
        if ctx.state.phase == "night" and any(enemy.hp > 0 for enemy in ctx.state.enemies):
            return ()

        pioneer = next(
            (a for a in ctx.state.characters if a.role == "pioneer"),
            None,
        )
        if pioneer is None:
            return ()

        traversability = TraversabilityMap.from_state_and_memory(
            ctx.state,
            ctx.world_memory,
            ctx.feedback_memory,
        )
        actions = []

        for task in ctx.state.tasks:
            if task.status != "available" or task.position is None:
                continue

            task_cells = task_zone_positions_for_task(ctx.state, task)
            if not task_cells:
                continue

            # TaskPoint itself is impassable interaction terrain. Once the
            # pioneer reaches the 8-neighborhood of ANY cell belonging to that
            # TaskPoint (TaskPoint2 spans two cells), approach is complete.
            if any(is_adjacent8(pioneer.position, cell) for cell in task_cells):
                continue

            access_cells = tuple(sorted({
                access
                for cell in task_cells
                for access in traversability.interaction_access_cells(cell)
            }, key=lambda p: (p.x, p.y)))
            step = _path_step(ctx, pioneer, access_cells)
            if step is None:
                continue

            if (
                ctx.feedback_memory is not None
                and ctx.feedback_memory.is_move_retry_blocked(
                    pioneer.actor_id,
                    step.x,
                    step.y,
                    ctx.state.round_id,
                )
            ):
                continue

            actions.append(
                GoalApproachAction(
                    actor_id=pioneer.actor_id,
                    action_type="move",
                    x=step.x,
                    y=step.y,
                    goal_kind="task",
                    goal_id=str(task.task_id),
                    goal_x=task.position.x,
                    goal_y=task.position.y,
                )
            )

        return tuple(actions)

class VendorApproachCandidateGenerator(CandidateGenerator):
    generator_id = "vendor_approach"
    tags = frozenset({"sell"})

    def generate(self, ctx, strategy):
        if ctx.state.phase != "day":
            return ()
        vendors = tuple(zone.position for zone in ctx.state.neutral_zones if zone.zone_type == "vendor")
        if not vendors:
            return ()
        traversability = TraversabilityMap.from_state_and_memory(ctx.state, ctx.world_memory, ctx.feedback_memory)
        access = tuple(sorted({cell for vendor in vendors for cell in traversability.interaction_access_cells(vendor)}, key=lambda p:(p.x,p.y)))
        actions = []
        for actor in ctx.state.characters:
            sellable = sum(sellable_amount(ctx.state, actor, name) for name in ctx.state.market_prices)
            if sellable <= 0 or any(is_adjacent8(actor.position, vendor) for vendor in vendors):
                continue
            step = _path_step(ctx, actor, access)
            if step is None:
                continue
            nearest = min(vendors, key=lambda p: chebyshev_distance(p, actor.position))
            actions.append(GoalApproachAction(
                actor_id=actor.actor_id, action_type="move", x=step.x, y=step.y,
                goal_kind="vendor", goal_id="vendor", goal_x=nearest.x, goal_y=nearest.y,
            ))
        return tuple(actions)


class WeaponShopApproachCandidateGenerator(CandidateGenerator):
    generator_id = "weapon_shop_approach"
    tags = frozenset({"buy"})

    def generate(self, ctx, strategy):
        if ctx.state.phase != "day" or ctx.state.gold_self <= 0:
            return ()
        shops = tuple(zone.position for zone in ctx.state.neutral_zones if zone.zone_type == "weaponShop")
        if not shops:
            return ()
        traversability = TraversabilityMap.from_state_and_memory(ctx.state, ctx.world_memory, ctx.feedback_memory)
        access = tuple(sorted({
            cell for shop in shops for cell in traversability.interaction_access_cells(shop)
        }, key=lambda p:(p.x,p.y)))
        builder_id = primary_builder_id(ctx.state)
        upgrade = next_upgrade_target(ctx.state)
        medicine_threshold = float(ctx.policy_state.thresholds.get("character_medicine_hp_ratio", 0.30))
        task_text = "\n".join((
            ctx.state.phase_task or "", ctx.state.last_command_result or "", ctx.state.raw_llm_response or ""
        )).casefold()
        standard_names = set(KNOWN_WEAPON_SHOP_PRICES)
        actions = []
        def affordable(name: str) -> bool:
            price = ctx.state.weapon_shop.get(name)
            if price is None:
                price = next((v for k, v in ctx.state.weapon_shop.items() if k.lower() == name.lower()), None)
            return price is not None and float(price) <= float(ctx.state.gold_self)

        for actor in ctx.state.characters:
            inv = _inventory(actor)
            needs_medicine = bool(
                actor.max_hp and actor.hp / max(1, actor.max_hp) < medicine_threshold
                and inv["medicine"] <= 0
                and affordable("Medicine")
            )
            needs_fixer = bool(
                str(actor.actor_id) == builder_id and ctx.state.day >= 2
                and inv["wallfixer"] <= 0
                and wall_fixer_target(ctx.state, actor, ctx.policy_state) is not None
                and affordable("WallFixer")
            )
            needs_upgrade = bool(
                str(actor.actor_id) == builder_id and upgrade is not None
                and inv[upgrade.voucher_name.lower()] <= 0
                and affordable(upgrade.voucher_name)
            )
            needs_task_item = False
            if actor.role == "pioneer" and ctx.state.phase_task.strip():
                needs_task_item = any(
                    name not in standard_names
                    and name.casefold() in task_text
                    and inv[name.lower()] <= 0
                    and affordable(name)
                    for name in ctx.state.weapon_shop
                )
            if not (needs_medicine or needs_fixer or needs_upgrade or needs_task_item):
                continue
            if any(is_adjacent8(actor.position, shop) for shop in shops):
                continue
            step = _path_step(ctx, actor, access)
            if step is None:
                continue
            nearest = min(shops, key=lambda p: chebyshev_distance(p, actor.position))
            actions.append(GoalApproachAction(
                actor_id=actor.actor_id, action_type="move", x=step.x, y=step.y,
                goal_kind="weapon_shop", goal_id="weaponShop", goal_x=nearest.x, goal_y=nearest.y,
            ))
        return tuple(actions)


class UseTargetApproachCandidateGenerator(CandidateGenerator):
    """已持有升级券/WallFixer 时前往唯一确定目标，补齐 buy→approach→use 闭环。"""

    generator_id = "use_target_approach"
    tags = frozenset({"use"})

    def generate(self, ctx, strategy):
        if ctx.state.phase != "day":
            return ()
        traversability = TraversabilityMap.from_state_and_memory(
            ctx.state, ctx.world_memory, ctx.feedback_memory
        )
        builder_id = primary_builder_id(ctx.state)
        upgrade = next_upgrade_target(ctx.state)
        actions = []
        for actor in ctx.state.characters:
            inv = _inventory(actor)
            target = None
            goal_kind = ""
            goal_id = ""
            rebuild = (
                wall_rebuild_target(ctx.state, actor, ctx.policy_state)
                if str(actor.actor_id) == builder_id else None
            )
            if rebuild is not None:
                target = rebuild.position
                goal_kind = "wall_rebuild"
                goal_id = str(rebuild.building_id)
            elif upgrade is not None and inv[upgrade.voucher_name.lower()] > 0:
                target = upgrade.position
                goal_kind = "upgrade_target"
                goal_id = upgrade.building_id
            elif str(actor.actor_id) == builder_id and ctx.state.day >= 2 and inv["wallfixer"] > 0:
                damaged = wall_fixer_target(ctx.state, actor, ctx.policy_state)
                if damaged is not None:
                    target = damaged.position
                    goal_kind = "wall_repair"
                    goal_id = str(damaged.building_id)
            if target is None or is_adjacent8(actor.position, target):
                continue
            access = tuple(sorted(traversability.interaction_access_cells(target), key=lambda p:(p.x,p.y)))
            step = _path_step(ctx, actor, access)
            if step is None:
                continue
            actions.append(GoalApproachAction(
                actor_id=actor.actor_id, action_type="move", x=step.x, y=step.y,
                goal_kind=goal_kind, goal_id=goal_id, goal_x=target.x, goal_y=target.y,
            ))
        return tuple(actions)


class WeaponBuildApproachCandidateGenerator(CandidateGenerator):
    """三座互补武器未完成时，让主建设者主动返回武器施工圈。"""

    generator_id = "weapon_build_approach"
    tags = frozenset({"build", "prepare"})

    def generate(self, ctx, strategy):
        if ctx.state.phase != "day" or weapon_count(ctx.state) >= 3 or ctx.state.gold_self < 25:
            return ()
        builder_id = primary_builder_id(ctx.state)
        if builder_id is None:
            return ()
        actor = next((a for a in ctx.state.characters if str(a.actor_id) == builder_id), None)
        if actor is None:
            return ()
        occupied = {
            (b.position.x, b.position.y)
            for b in ctx.state.buildings
            if b.owner == "self"
        }
        cluster = rocket_cluster_plan(ctx.state)
        if cluster is None:
            return ()
        # Approach 与 BuildCandidate 必须共享完全相同的三武器固定目标，
        # 否则 Worker 可能走向一个普通 weapon-ring cell，到了以后却无塔可建。
        targets = [
            Position(x, y) for x, y in cluster.rocket_cells
            if (x, y) not in occupied
        ]
        if not targets:
            return ()
        traversability = TraversabilityMap.from_state_and_memory(
            ctx.state, ctx.world_memory, ctx.feedback_memory
        )
        actions = []
        lookahead = max(1, int(ctx.policy_state.thresholds.get("build_target_lookahead", 4.0)))
        for target in targets[:lookahead]:
            if is_adjacent8(actor.position, target):
                continue
            access = tuple(sorted(
                traversability.interaction_access_cells(target),
                key=lambda p: (p.x, p.y),
            ))
            step = _path_step(ctx, actor, access)
            if step is None:
                continue
            actions.append(GoalApproachAction(
                actor_id=actor.actor_id,
                action_type="move",
                x=step.x,
                y=step.y,
                goal_kind="weapon_build",
                goal_id=f"weapon:{target.x}:{target.y}",
                goal_x=target.x,
                goal_y=target.y,
            ))
            break
        return tuple(actions)


class WallBuildApproachCandidateGenerator(CandidateGenerator):
    """三塔成形后，把携带 stone 的 Worker 主动送回外圈施工位。

    旧实现只有“已经站在墙位旁时才有 BuildAction”，矿工采完 stone 后可能继续
    留在矿区。这里把“返场施工”显式建模为 GoalApproachAction。
    """

    generator_id = "wall_build_approach"
    tags = frozenset({"build", "prepare"})

    def generate(self, ctx, strategy):
        if ctx.state.phase != "day" or weapon_count(ctx.state) < 3 or wall_blueprint_complete(ctx.state):
            return ()
        existing_walls = {
            (b.position.x, b.position.y)
            for b in ctx.state.buildings
            if b.owner == "self" and b.building_type == "wall"
        }
        ordered_targets = [
            Position(x, y) for x, y in ordered_wall_build_cells(ctx.state)
            if (x, y) not in existing_walls
        ]
        if not ordered_targets:
            return ()
        traversability = TraversabilityMap.from_state_and_memory(
            ctx.state, ctx.world_memory, ctx.feedback_memory
        )
        actions = []
        for actor in ctx.state.characters:
            if actor.role != "worker":
                continue
            stone = _inventory(actor)["stone"]
            if stone <= 0:
                continue
            # 正常阶段：离开矿点后达到 stone 批量再返场。
            # 施工预留窗口：只有背包矿物达到 near-night 配置比例才提前返场。
            # 紧急窗口：只要手上有 stone 就立即返场。
            batch_target = stone_batch_target(ctx.state, actor, ctx.policy_state)
            wall_due = wall_construction_due(ctx.state, ctx.policy_state)
            urgent = in_mining_emergency_window(ctx.state, ctx.policy_state)
            near_night_due = near_night_mineral_return_due(ctx.state, actor, ctx.policy_state)
            if wall_due and not urgent and not near_night_due and stone < batch_target:
                continue
            # 只看配置的高优先级墙位数量，避免为 20 个目标重复跑 A*。
            lookahead = max(1, int(ctx.policy_state.thresholds.get("build_target_lookahead", 4.0)))
            for target in ordered_targets[:lookahead]:
                if is_adjacent8(actor.position, target):
                    continue
                access = tuple(sorted(
                    traversability.interaction_access_cells(target),
                    key=lambda p: (p.x, p.y),
                ))
                step = _path_step(ctx, actor, access)
                if step is None:
                    continue
                actions.append(GoalApproachAction(
                    actor_id=actor.actor_id,
                    action_type="move",
                    x=step.x,
                    y=step.y,
                    goal_kind="wall_build",
                    goal_id=f"wall:{target.x}:{target.y}",
                    goal_x=target.x,
                    goal_y=target.y,
                ))
                break
        return tuple(actions)


class BaseReturnCandidateGenerator(CandidateGenerator):
    """Prepare 阶段：Pioneer 回公共 Rocket 控制点；Worker 回基地/施工圈。

    Pioneer 即使正在执行自进化任务也允许在夜前主动离开 TaskPoint。离开会结束
    当前任务，但这是合法的战略选择，不是协议错误；生存/夜战优先。
    """

    generator_id = "base_return"
    tags = frozenset({"prepare"})

    def generate(self, ctx, strategy):
        if ctx.state.phase != "day":
            return ()
        station = next((
            b for b in ctx.state.buildings
            if b.owner == "self" and b.building_type == "station"
        ), None)
        if station is None:
            return ()
        traversability = TraversabilityMap.from_state_and_memory(
            ctx.state, ctx.world_memory, ctx.feedback_memory
        )
        footprint = BuildingFootprintResolver.cells(
            station, map_width=ctx.state.map_width, map_height=ctx.state.map_height
        )
        station_ring = {
            pos for cell in footprint
            for pos in traversability.walkable_neighbors(cell.x, cell.y)
        }
        plan = rocket_cluster_plan(ctx.state)
        actions = []
        for actor in ctx.state.characters:
            if actor.hp <= 0:
                continue
            if actor.role == "pioneer" and ctx.state.phase_task.strip():
                # Once accepted, keep the Pioneer anchored so the task session
                # can finish. Night combat may still override this via the
                # higher-priority defense strategy when enemies are present.
                continue
            if actor.role == "pioneer" and plan is not None:
                controller = Position(*plan.controller)
                if actor.position == controller:
                    continue
                goals = (controller,) if traversability.is_walkable(controller.x, controller.y) else ()
                step = _path_step(ctx, actor, goals)
                if step is None:
                    continue
                actions.append(GoalApproachAction(
                    actor_id=actor.actor_id, action_type="move",
                    x=step.x, y=step.y,
                    goal_kind="rocket_controller", goal_id="rocket_cluster_controller",
                    goal_x=controller.x, goal_y=controller.y,
                ))
                continue

            if actor.role != "worker":
                continue
            # Carrying stone + unfinished blueprint is handled by WallBuildApproach,
            # otherwise prepare simply brings the Worker into the base ring.
            if _inventory(actor)["stone"] > 0 and wall_blueprint_missing_count(ctx.state) > 0:
                continue
            goals = tuple(sorted(station_ring, key=lambda p: (p.x, p.y)))
            if not goals or actor.position in goals:
                continue
            step = _path_step(ctx, actor, goals)
            if step is None:
                continue
            goal = min(goals, key=lambda p: chebyshev_distance(p, actor.position))
            actions.append(GoalApproachAction(
                actor_id=actor.actor_id, action_type="move",
                x=step.x, y=step.y,
                goal_kind="base", goal_id=str(station.building_id),
                goal_x=goal.x, goal_y=goal.y,
            ))
        return tuple(actions)


class DefensePostCandidateGenerator(CandidateGenerator):
    """夜间仅把 Pioneer 送到三武器布局的公共控制点。

    Worker 不再被拉去抢武器控制位；它们由 NightResourceApproach / Retreat
    决定是否在地图边缘安全采矿。Pioneer 的 Safe A* 会避开机器人未来进攻走廊。
    """

    generator_id = "defense_post"
    tags = frozenset({"defense"})

    def generate(self, ctx, strategy):
        if ctx.state.phase != "night":
            return ()
        # 机器人已经清空时让 Pioneer 重新进入任务流程，不继续死守炮位。
        if not any(enemy.hp > 0 for enemy in ctx.state.enemies):
            return ()
        pioneer = next((
            actor for actor in ctx.state.characters
            if actor.role == "pioneer" and actor.hp > 0
        ), None)
        if pioneer is None:
            return ()
        plan = rocket_cluster_plan(ctx.state)
        if plan is None:
            return ()
        controller = Position(*plan.controller)
        if pioneer.position == controller:
            return ()
        traversability = TraversabilityMap.from_state_and_memory(
            ctx.state, ctx.world_memory, ctx.feedback_memory
        )
        if not traversability.is_walkable(controller.x, controller.y):
            return ()
        step = _safe_path_step(ctx, pioneer, (controller,))
        if step is None:
            return ()
        return (GoalApproachAction(
            actor_id=pioneer.actor_id,
            action_type="move",
            x=step.x, y=step.y,
            goal_kind="rocket_controller",
            goal_id="rocket_cluster_controller",
            goal_x=controller.x, goal_y=controller.y,
        ),)
