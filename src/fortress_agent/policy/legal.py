from __future__ import annotations

from collections import Counter
from itertools import combinations

from fortress_agent.domain.action import (
    AcceptTaskAction,
    AttackAction,
    BuildAction,
    BuyAction,
    DropAction,
    ExploreAction,
    GatherAction,
    MoveAction,
    RemoveAction,
    SellAction,
    SubmitAnswerAction,
    SummonTreasureAction,
    UseAction,
)
from fortress_agent.game_rules.catalog import WEAPON_TYPES, building_rule, weapon_attack_range
from fortress_agent.game_rules.build_area import BuildAreaPolicy, DEFAULT_BUILD_AREA_POLICY
from fortress_agent.game_rules.geometry import angle_within_90, chebyshev_distance, is_adjacent8
from fortress_agent.game_rules.tasks import available_task_zone_positions, active_task_anchor_positions
from fortress_agent.memory.resources import ResourceStatus
from fortress_agent.policy.context import PolicyContext
from fortress_agent.world.traversability import TraversabilityMap
from fortress_agent.game_rules.night_safety import threat_field, night_gather_is_safe


class BasicLegalActionFilter:
    def __init__(self, build_area_policy: BuildAreaPolicy | None = None) -> None:
        self._build_area_policy = build_area_policy or DEFAULT_BUILD_AREA_POLICY

    def is_legal(self, ctx: PolicyContext, action) -> bool:
        if ctx.feedback_memory is not None and ctx.feedback_memory.is_action_forbidden(action, ctx.state.round_id):
            return False

        if isinstance(action, AttackAction):
            return self._attack(ctx, action)

        actor = next((a for a in ctx.state.characters if a.actor_id == action.actor_id), None)
        if actor is None or actor.hp <= 0:
            return False

        if isinstance(action, (MoveAction, ExploreAction)):
            if not self._inside(ctx, action.x, action.y):
                return False
            if not is_adjacent8(actor.position, (action.x, action.y)):
                return False
            if ctx.feedback_memory is not None and ctx.feedback_memory.is_move_retry_blocked(
                actor.actor_id, action.x, action.y, ctx.state.round_id
            ):
                return False
            traversability = TraversabilityMap.from_state_and_memory(
                ctx.state, ctx.world_memory, ctx.feedback_memory
            )
            if not traversability.is_walkable(action.x, action.y):
                return False
            if ctx.state.phase == "night" and actor.role == "worker":
                from fortress_agent.domain.state import Position
                field = threat_field(ctx)
                if max(field.risk(Position(action.x, action.y), eta) for eta in (0, 1)) >= 1.0:
                    return False

            # Leaving an active TaskPoint is a legal game action that *ends the
            # task*; it is not an instruction-format error. Candidate/Doctrine
            # normally anchors Pioneer, but prepare/night survival is allowed to
            # intentionally abandon the task and return to the Rocket controller.
            return True

        if isinstance(action, GatherAction):
            if ctx.state.phase not in {"day", "night"} or actor.role != "worker":
                return False
            resource = ctx.world_memory.resource(action.resource_id)
            if resource is None or resource.status is not ResourceStatus.AVAILABLE:
                return False
            if ctx.state.phase == "night" and not night_gather_is_safe(ctx, actor, resource):
                return False
            return is_adjacent8(actor.position, (resource.x, resource.y))

        if isinstance(action, SellAction):
            if ctx.state.phase != "day" or action.num <= 0:
                return False
            if not self._near_zone(ctx, actor, "vendor"):
                return False
            inventory = self._inventory(actor)
            return action.name.lower() in ctx.state.market_prices and inventory[action.name.lower()] >= action.num

        if isinstance(action, BuyAction):
            if ctx.state.phase != "day" or action.num <= 0:
                return False
            if not self._near_zone(ctx, actor, "weaponShop"):
                return False
            price = self._shop_price(ctx, action.name)
            return price is not None and price * action.num <= ctx.state.gold_self

        if isinstance(action, BuildAction):
            return self._build(ctx, actor, action)

        if isinstance(action, RemoveAction):
            if actor.role != "worker" or not is_adjacent8(actor.position, action.target):
                return False
            return any(
                b.owner == "self" and b.building_type == "wall" and b.position == action.target
                for b in ctx.state.buildings
            )

        if isinstance(action, AcceptTaskAction):
            if ctx.state.phase != "day" or actor.role != "pioneer" or ctx.state.phase_task.strip():
                return False
            return any(
                is_adjacent8(actor.position, pos)
                for pos in available_task_zone_positions(ctx.state)
            )

        if isinstance(action, SubmitAnswerAction):
            return actor.role == "pioneer" and bool(ctx.state.phase_task.strip()) and bool(action.task_answer.strip())

        if isinstance(action, SummonTreasureAction):
            if actor.role != "pioneer" or not action.items or not is_adjacent8(actor.position, action.target):
                return False
            inventory = self._inventory(actor)
            required = Counter(item.lower() for item in action.items)
            return all(inventory[item] >= amount for item, amount in required.items())

        if isinstance(action, UseAction):
            return self._use(ctx, actor, action)

        if isinstance(action, DropAction):
            inventory = self._inventory(actor)
            return bool(action.name.strip()) and inventory[action.name.lower()] > 0

        return False

    def _build(self, ctx, actor, action: BuildAction) -> bool:
        name = action.name.lower()
        rule = building_rule(name)
        if ctx.state.phase != "day" or actor.role != "worker" or rule is None or name == "station":
            return False
        if not self._inside(ctx, action.target.x, action.target.y) or not is_adjacent8(actor.position, action.target):
            return False
        if not self._build_area_policy.permits(
            building_name=name,
            target=action.target,
            state=ctx.state,
        ):
            return False
        inventory = self._inventory(actor)
        if any(inventory[item] < amount for item, amount in rule.build_items):
            return False
        if ctx.state.gold_self < rule.build_gold_cost:
            return False

        own = [b for b in ctx.state.buildings if b.owner == "self"]
        existing_at = next((b for b in own if b.position == action.target), None)
        if name in WEAPON_TYPES:
            current_weapons = [b for b in own if b.building_type in WEAPON_TYPES]
            replacing = existing_at is not None and existing_at.building_type in WEAPON_TYPES
            if len(current_weapons) >= 3 and not replacing:
                return False
            if existing_at is not None and not replacing:
                return False
            if existing_at is None:
                traversability = TraversabilityMap.from_state_and_memory(ctx.state, ctx.world_memory, ctx.feedback_memory)
                if not traversability.is_walkable(action.target.x, action.target.y):
                    return False
            return True

        if name == "wall":
            if sum(1 for b in own if b.building_type == "wall") >= 20:
                return False
            traversability = TraversabilityMap.from_state_and_memory(ctx.state, ctx.world_memory, ctx.feedback_memory)
            return traversability.is_walkable(action.target.x, action.target.y)
        return False

    def _use(self, ctx, actor, action: UseAction) -> bool:
        inventory = self._inventory(actor)
        name = action.name.strip()
        lname = name.lower()
        if not name or inventory[lname] <= 0:
            return False

        if name == "Medicine":
            return action.target is None

        if name in {"DizzyWeapon", "Bomb"}:
            return action.target is not None and self._inside(ctx, action.target.x, action.target.y)

        if name in {"SmallRobotSummonOrder", "MiddleRobotSummonOrder", "LargeRobotSummonOrder", "BossRobotSummonOrder"}:
            return action.target is None

        if action.target is None or not self._inside(ctx, action.target.x, action.target.y):
            return False

        target_building = next((
            b for b in ctx.state.buildings
            if b.owner == "self" and b.position == action.target
        ), None)
        if target_building is None or not is_adjacent8(actor.position, target_building.position):
            return False

        if name == "WallFixer":
            return target_building.building_type == "wall" and target_building.max_hp is not None and target_building.hp is not None and target_building.hp < target_building.max_hp

        voucher_specs = {
            "WeaponUpgradeVoucher1": (WEAPON_TYPES, 1),
            "WeaponUpgradeVoucher2": (WEAPON_TYPES, 2),
            "WallUpgradeVoucher1": ({"wall"}, 1),
            "WallUpgradeVoucher2": ({"wall"}, 2),
            "StationUpgradeVoucher1": ({"station"}, 1),
            "StationUpgradeVoucher2": ({"station"}, 2),
        }
        spec = voucher_specs.get(name)
        if spec is not None:
            types, required_level = spec
            return target_building.building_type in types and int(target_building.level or 1) == required_level

        # Task supplies are consumed through summonTreasure rather than use.
        return False

    def _attack(self, ctx: PolicyContext, action: AttackAction) -> bool:
        if ctx.state.phase != "night":
            return False
        weapon = next((b for b in ctx.state.buildings if b.building_id == action.actor_id), None)
        controller = next((c for c in ctx.state.characters if c.actor_id == action.controller_id), None)
        if (
            weapon is None or weapon.owner != "self" or weapon.building_type not in WEAPON_TYPES
            or controller is None or controller.hp <= 0
            or not is_adjacent8(controller.position, weapon.position)
        ):
            return False
        expected = 1 if weapon.building_type == "railgun" else max(1, int(weapon.level or 1))
        if len(action.targets) != expected or len(set((p.x, p.y) for p in action.targets)) != len(action.targets):
            return False
        if any(not self._inside(ctx, p.x, p.y) for p in action.targets):
            return False
        if weapon.building_type == "rocket" and weapon.cooldown_remaining > 0:
            return False

        for target in action.targets:
            if weapon.building_type == "rocket" and int(weapon.level or 1) >= 3:
                continue
            server_range = int(weapon.attack_range or 0)
            official_range = weapon_attack_range(weapon.building_type, weapon.level)
            if official_range is None:
                continue
            effective = int(official_range) if server_range <= 0 else min(server_range, int(official_range))
            if chebyshev_distance(weapon.position, target) > effective:
                return False

        if weapon.building_type == "gatling" and any(
            not angle_within_90(weapon.position, a, b)
            for a, b in combinations(action.targets, 2)
        ):
            return False
        return True

    @staticmethod
    def _inventory(actor) -> Counter[str]:
        return Counter({item.item_type.lower(): item.amount for item in actor.inventory})

    @staticmethod
    def _inside(ctx: PolicyContext, x: int, y: int) -> bool:
        return 0 <= x < ctx.state.map_width and 0 <= y < ctx.state.map_height

    @staticmethod
    def _shop_price(ctx: PolicyContext, name: str) -> float | None:
        if name in ctx.state.weapon_shop:
            return float(ctx.state.weapon_shop[name])
        lname = name.lower()
        for key, value in ctx.state.weapon_shop.items():
            if key.lower() == lname:
                return float(value)
        return None

    @staticmethod
    def _near_zone(ctx: PolicyContext, actor, zone_type: str) -> bool:
        return any(
            zone.zone_type == zone_type and is_adjacent8(actor.position, zone.position)
            for zone in ctx.state.neutral_zones
        )


    def filter(self, ctx: PolicyContext, actions: tuple):
        return tuple(action for action in actions if self.is_legal(ctx, action))
