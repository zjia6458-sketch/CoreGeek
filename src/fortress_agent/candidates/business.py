from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from fortress_agent.domain.action import (
    AcceptTaskAction,
    BuildAction,
    BuyAction,
    RemoveAction,
    SellAction,
    SubmitAnswerAction,
    SummonTreasureAction,
    UseAction,
)
from fortress_agent.domain.state import Position
from fortress_agent.game_rules.catalog import WEAPON_TYPES, KNOWN_WEAPON_SHOP_PRICES
from fortress_agent.game_rules.upgrades import next_upgrade_target
from fortress_agent.game_rules.economy import (
    next_weapon_build_type,
    primary_builder_id,
    wall_fixer_target,
    wall_rebuild_target,
)
from fortress_agent.game_rules.build_area import (
    BuildAreaPolicy, DEFAULT_BUILD_AREA_POLICY, rocket_cluster_plan,
    ordered_wall_build_cells, wall_blueprint_complete,
)
from fortress_agent.game_rules.geometry import is_adjacent8, neighbors8
from fortress_agent.game_rules.economy import sellable_amount
from fortress_agent.game_rules.tasks import available_task_zone_positions, task_zone_positions_for_task
from fortress_agent.policy.build_catalog import BuildCatalog
from fortress_agent.policy.context import PolicyContext
from fortress_agent.world.traversability import TraversabilityMap

from .base import CandidateGenerator


def _zone_positions(ctx: PolicyContext, zone_type: str) -> tuple[Position, ...]:
    return tuple(
        zone.position
        for zone in ctx.state.neutral_zones
        if zone.zone_type == zone_type
    )


def _inventory(actor) -> Counter[str]:
    return Counter({item.item_type.lower(): item.amount for item in actor.inventory})


def _near_any(actor, positions: tuple[Position, ...]) -> bool:
    return any(is_adjacent8(actor.position, position) for position in positions)


class SellCandidateGenerator(CandidateGenerator):
    generator_id = "sell"
    tags = frozenset({"sell"})

    def generate(self, ctx, strategy):
        if ctx.state.phase != "day":
            return ()
        vendors = _zone_positions(ctx, "vendor")
        if not vendors:
            return ()
        actions = []
        for actor in ctx.state.characters:
            if not _near_any(actor, vendors):
                continue
            for mineral in sorted(ctx.state.market_prices):
                amount = sellable_amount(ctx.state, actor, mineral)
                if amount <= 0:
                    continue
                # Batch selling is explicitly supported. Selling the full stack
                # avoids wasting one action per mineral unit.
                actions.append(SellAction(
                    actor_id=actor.actor_id,
                    action_type="sell",
                    name=mineral,
                    num=amount,
                ))
        return tuple(actions)


class RemoveCandidateGenerator(CandidateGenerator):
    """Replace a critically damaged wall when stone is already available."""

    generator_id = "remove_wall"
    tags = frozenset({"build", "prepare", "use"})

    def generate(self, ctx, strategy):
        if ctx.state.phase != "day":
            return ()
        builder_id = primary_builder_id(ctx.state)
        actor = next((
            a for a in ctx.state.characters
            if str(a.actor_id) == builder_id and a.hp > 0
        ), None)
        if actor is None:
            return ()
        target = wall_rebuild_target(ctx.state, actor, ctx.policy_state)
        if target is None or not is_adjacent8(actor.position, target.position):
            return ()
        return (RemoveAction(
            actor_id=actor.actor_id,
            action_type="remove",
            target=target.position,
        ),)


class BuyCandidateGenerator(CandidateGenerator):
    generator_id = "buy"
    tags = frozenset({"buy"})

    def generate(self, ctx, strategy):
        if ctx.state.phase != "day":
            return ()
        shops = _zone_positions(ctx, "weaponShop")
        if not shops:
            return ()
        actions = []
        builder_id = primary_builder_id(ctx.state)
        upgrade = next_upgrade_target(ctx.state)
        task_text = "\n".join((
            ctx.state.phase_task or "",
            ctx.state.last_command_result or "",
            ctx.state.raw_llm_response or "",
        )).casefold()
        standard_names = set(KNOWN_WEAPON_SHOP_PRICES)

        for actor in ctx.state.characters:
            if not _near_any(actor, shops):
                continue
            inventory = _inventory(actor)
            desired: list[str] = []

            # Survival override: only below configured 30% HP, not merely damaged.
            if actor.max_hp:
                ratio = actor.hp / max(1, actor.max_hp)
                threshold = float(ctx.policy_state.thresholds.get("character_medicine_hp_ratio", 0.30))
                if ratio < threshold and inventory["medicine"] <= 0:
                    desired.append("Medicine")

            # Day2+ one Worker maintains seriously damaged walls.
            if str(actor.actor_id) == builder_id and ctx.state.day >= 2:
                damaged = wall_fixer_target(ctx.state, actor, ctx.policy_state) is not None
                if damaged and inventory["wallfixer"] <= 0:
                    desired.append("WallFixer")

            # Economy/upgrade phase: Planner exposes exactly one next voucher.
            if str(actor.actor_id) == builder_id and upgrade is not None:
                if inventory[upgrade.voucher_name.lower()] <= 0:
                    desired.append(upgrade.voucher_name)

            # Active task supplies: only buy a non-standard shop item when its
            # exact name is explicitly mentioned by task/command feedback.
            if actor.role == "pioneer" and ctx.state.phase_task.strip():
                for item_name in ctx.state.weapon_shop:
                    if item_name in standard_names:
                        continue
                    if item_name.casefold() in task_text and inventory[item_name.lower()] <= 0:
                        desired.append(item_name)

            for item_name in dict.fromkeys(desired):
                price = ctx.state.weapon_shop.get(item_name)
                if price is None or price > ctx.state.gold_self:
                    continue
                actions.append(BuyAction(
                    actor_id=actor.actor_id,
                    action_type="buy",
                    name=item_name,
                    num=1,
                ))
        return tuple(actions)


class UseCandidateGenerator(CandidateGenerator):
    generator_id = "use"
    tags = frozenset({"use"})

    def generate(self, ctx, strategy):
        actions = []
        buildings = tuple(b for b in ctx.state.buildings if b.owner == "self")
        builder_id = primary_builder_id(ctx.state)
        upgrade = next_upgrade_target(ctx.state)
        medicine_threshold = float(ctx.policy_state.thresholds.get("character_medicine_hp_ratio", 0.30))

        for actor in ctx.state.characters:
            inventory = _inventory(actor)
            if (
                inventory["medicine"] > 0
                and actor.max_hp
                and actor.hp / max(1, actor.max_hp) < medicine_threshold
            ):
                actions.append(UseAction(
                    actor_id=actor.actor_id, action_type="use", name="Medicine"
                ))

            if str(actor.actor_id) == builder_id and ctx.state.day >= 2 and inventory["wallfixer"] > 0:
                wall = wall_fixer_target(ctx.state, actor, ctx.policy_state)
                if wall is not None and not is_adjacent8(actor.position, wall.position):
                    wall = None
                if wall is not None:
                    actions.append(UseAction(
                        actor_id=actor.actor_id, action_type="use",
                        name="WallFixer", target=wall.position,
                    ))

            if upgrade is not None and inventory[upgrade.voucher_name.lower()] > 0:
                target = next((
                    b for b in buildings
                    if str(b.building_id) == upgrade.building_id
                    and is_adjacent8(actor.position, b.position)
                ), None)
                if target is not None:
                    actions.append(UseAction(
                        actor_id=actor.actor_id,
                        action_type="use",
                        name=upgrade.voucher_name,
                        target=target.position,
                    ))
        return tuple(actions)


class AcceptTaskCandidateGenerator(CandidateGenerator):
    generator_id = "accept_task"
    tags = frozenset({"task", "defense"})

    def generate(self, ctx, strategy):
        if ctx.state.phase not in {"day", "night"} or ctx.state.phase_task.strip():
            return ()
        if ctx.state.phase == "night" and any(enemy.hp > 0 for enemy in ctx.state.enemies):
            return ()
        # 自进化任务要求 Pioneer 全程留在 TaskPoint 邻域。按任务 timeout
        # 预留完成窗口，避免“刚接取就进入 prepare/夜晚”的必败会话。
        valid_task_zones = available_task_zone_positions(ctx.state)
        actions = []
        for actor in ctx.state.characters:
            if actor.role != "pioneer":
                continue
            nearby_tasks = [
                task for task in ctx.state.tasks
                if task.status == "available"
                and _near_any(actor, task_zone_positions_for_task(ctx.state, task))
            ]
            if not nearby_tasks or not valid_task_zones:
                continue
            task_windows = [
                min(30, int(task.timeout_rounds))
                for task in nearby_tasks if task.timeout_rounds
            ]
            required_window = max(15, max(task_windows, default=15))
            if (
                ctx.state.phase == "day"
                and ctx.state.turns_until_phase_change is not None
                and ctx.state.turns_until_phase_change <= required_window
            ):
                continue
            actions.append(AcceptTaskAction(actor_id=actor.actor_id, action_type="acceptTask"))
        return tuple(actions)


class TaskAnswerProvider(Protocol):
    def answer(self, ctx: PolicyContext) -> str | None: ...


class NoOpTaskAnswerProvider:
    def answer(self, ctx):
        return None


class SubmitAnswerCandidateGenerator(CandidateGenerator):
    generator_id = "submit_answer"
    tags = frozenset({"task"})

    def __init__(self, provider: TaskAnswerProvider | None = None) -> None:
        self._provider = provider or NoOpTaskAnswerProvider()

    def generate(self, ctx, strategy):
        if not ctx.state.phase_task.strip():
            return ()
        answer = self._provider.answer(ctx)
        if not answer or not answer.strip():
            return ()
        pioneer = next((actor for actor in ctx.state.characters if actor.role == "pioneer"), None)
        if pioneer is None:
            return ()
        return (SubmitAnswerAction(actor_id=pioneer.actor_id, action_type="submitAnswer", task_answer=answer.strip()),)


@dataclass(frozen=True, slots=True)
class TreasurePlan:
    target: Position
    items: tuple[str, ...]


class TreasurePlanProvider(Protocol):
    def plan(self, ctx: PolicyContext) -> TreasurePlan | None: ...


class NoOpTreasurePlanProvider:
    def plan(self, ctx):
        return None


class SummonTreasureCandidateGenerator(CandidateGenerator):
    generator_id = "summon_treasure"
    tags = frozenset({"treasure"})

    def __init__(self, provider: TreasurePlanProvider | None = None) -> None:
        self._provider = provider or NoOpTreasurePlanProvider()

    def generate(self, ctx, strategy):
        plan = self._provider.plan(ctx)
        if plan is None or not plan.items:
            return ()
        pioneer = next((actor for actor in ctx.state.characters if actor.role == "pioneer"), None)
        if pioneer is None or not is_adjacent8(pioneer.position, plan.target):
            return ()
        return (SummonTreasureAction(
            actor_id=pioneer.actor_id,
            action_type="summonTreasure",
            target=plan.target,
            items=plan.items,
        ),)


class BuildCandidateGenerator(CandidateGenerator):
    generator_id = "build"
    tags = frozenset({"build", "prepare"})

    def __init__(
        self,
        catalog: BuildCatalog | None = None,
        build_area_policy: BuildAreaPolicy | None = None,
    ) -> None:
        self._catalog = catalog or BuildCatalog.official_default()
        self._build_area_policy = build_area_policy or DEFAULT_BUILD_AREA_POLICY

    def generate(self, ctx, strategy):
        if ctx.state.phase != "day":
            return ()
        recipes = self._catalog.recipes()
        if not recipes:
            return ()
        traversability = TraversabilityMap.from_state_and_memory(
            ctx.state, ctx.world_memory, ctx.feedback_memory
        )
        actions = []
        existing_weapons = [
            b for b in ctx.state.buildings
            if b.owner == "self" and b.building_type in WEAPON_TYPES
        ]
        existing_walls = [
            b for b in ctx.state.buildings
            if b.owner == "self" and b.building_type == "wall"
        ]
        building_at = {
            (b.position.x, b.position.y): b
            for b in ctx.state.buildings if b.owner == "self"
        }
        alive_workers = sorted(
            (actor for actor in ctx.state.characters if actor.role == "worker" and actor.hp > 0),
            key=lambda actor: str(actor.actor_id),
        )
        primary_builder_id = str(alive_workers[0].actor_id) if alive_workers else None
        cluster = rocket_cluster_plan(ctx.state)
        cluster_cells = set(cluster.rocket_cells) if cluster is not None else set()
        desired_weapon_type = next_weapon_build_type(ctx.state)
        explicit_wall_cells = tuple(sorted(getattr(self._build_area_policy, "wall_cells", ()) or ()))
        wall_order = (
            explicit_wall_cells
            if explicit_wall_cells
            else ordered_wall_build_cells(ctx.state)
        )
        missing_wall_order = [
            cell for cell in wall_order
            if cell not in {(b.position.x, b.position.y) for b in existing_walls}
        ]
        lookahead = max(1, int(ctx.policy_state.thresholds.get("build_target_lookahead", 4.0)))
        allowed_wall_targets = set(missing_wall_order[:lookahead])

        for worker in ctx.state.characters:
            if worker.role != "worker" or worker.hp <= 0:
                continue
            inventory = _inventory(worker)
            for recipe in recipes:
                name = recipe.building_name.lower()

                # Fill the three clustered slots with early-game Rockets.
                if name in WEAPON_TYPES:
                    if len(existing_weapons) >= 3:
                        continue
                    if name != desired_weapon_type:
                        continue
                    if primary_builder_id is None or str(worker.actor_id) != primary_builder_id:
                        continue
                    if cluster is None:
                        continue

                if name == "wall":
                    # Standard opening builds its weapon force before walls.
                    # Explicit wall-only catalogs remain usable for custom maps.
                    if len(existing_weapons) < 3 and any(
                        r.building_name.lower() in WEAPON_TYPES for r in recipes
                    ):
                        continue
                    if (not explicit_wall_cells and wall_blueprint_complete(ctx.state)) or not allowed_wall_targets:
                        continue
                    if len(existing_walls) >= 20:
                        continue
                    # Day2+ 防线维修/重建由主建设者负责，另一 Worker 保持经济循环。
                    if ctx.state.day >= 2 and (primary_builder_id is None or str(worker.actor_id) != primary_builder_id):
                        continue

                if recipe.gold_cost > ctx.state.gold_self:
                    continue
                if any(inventory[item.lower()] < amount for item, amount in recipe.required_items.items()):
                    continue

                for x, y in neighbors8(worker.position.x, worker.position.y):
                    target = (x, y)
                    if not (0 <= x < ctx.state.map_width and 0 <= y < ctx.state.map_height):
                        continue
                    if name in WEAPON_TYPES and target not in cluster_cells:
                        continue
                    if name == "wall" and target not in allowed_wall_targets:
                        continue
                    existing = building_at.get(target)
                    if not self._build_area_policy.permits(
                        building_name=name,
                        target=target,
                        state=ctx.state,
                    ):
                        continue
                    if name in WEAPON_TYPES:
                        # During initial composition, never overwrite an
                        # existing weapon: fill an empty slot first.
                        if existing is not None:
                            continue
                        if not traversability.is_walkable(x, y):
                            continue
                    elif name == "wall":
                        if existing is not None or not traversability.is_walkable(x, y):
                            continue
                    else:
                        continue
                    actions.append(BuildAction(
                        actor_id=worker.actor_id,
                        action_type="build",
                        name=name,
                        target=Position(x, y),
                    ))
        return tuple(actions)
