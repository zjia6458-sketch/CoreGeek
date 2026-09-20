from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations

from fortress_agent.domain.state import GameState, Position
from fortress_agent.game_rules.catalog import WEAPON_TYPES, building_rule, weapon_attack_range
from fortress_agent.game_rules.build_area import BuildAreaPolicy, DEFAULT_BUILD_AREA_POLICY
from fortress_agent.game_rules.geometry import angle_within_90, chebyshev_distance, is_adjacent8
from fortress_agent.game_rules.tasks import available_task_zone_positions, active_task_anchor_positions
from fortress_agent.world.traversability import TraversabilityMap
from fortress_agent.world.safe_pathfinding import RobotThreatConfig, RobotThreatField

from .server_outbound import (
    AcceptTaskRoleCommand,
    AttackRoleCommand,
    BuildRoleCommand,
    BuyRoleCommand,
    CollectRoleCommand,
    DropRoleCommand,
    MoveRoleCommand,
    RemoveRoleCommand,
    RoleCommand,
    SellRoleCommand,
    ServerCommandResponse,
    SubmitAnswerRoleCommand,
    SummonTreasureRoleCommand,
    UseRoleCommand,
)


@dataclass(frozen=True, slots=True)
class FinalValidationIssue:
    code: str
    message: str
    role_id: str | None = None


@dataclass(frozen=True, slots=True)
class FinalValidationResult:
    valid_commands: dict[str, RoleCommand]
    rejected_roles: tuple[str, ...]
    top_level_issues: tuple[FinalValidationIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.rejected_roles and not self.top_level_issues


class FinalResponseValidator:
    """Last state-aware safety gate before serialization.

    It enforces confirmed protocol constraints plus the conservative worker
    night-safety doctrine. Ordinary execution failures such as collisions are not
    treated as response-format anomalies, but obvious known blockers and
    self-conflicts are still suppressed to avoid wasting turns.
    """

    def __init__(self, build_area_policy: BuildAreaPolicy | None = None) -> None:
        self._build_area_policy = build_area_policy or DEFAULT_BUILD_AREA_POLICY

    def validate(self, *, state: GameState, response: ServerCommandResponse, llm_call_allowed: bool = True, world_memory=None, feedback_memory=None) -> FinalValidationResult:
        valid: dict[str, RoleCommand] = {}
        rejected: list[str] = []
        top: list[FinalValidationIssue] = []

        own_characters = {str(x.actor_id): x for x in state.characters}
        own_buildings = {str(x.building_id): x for x in state.buildings if x.owner == "self"}
        controller_usage: Counter[str] = Counter()

        for role_id, command in response.roleCommandMap.items():
            issue = self._validate_command(
                state=state,
                role_id=role_id,
                command=command,
                own_characters=own_characters,
                own_buildings=own_buildings,
                world_memory=world_memory,
                feedback_memory=feedback_memory,
            )
            if issue is not None:
                rejected.append(role_id)
                continue
            if isinstance(command, AttackRoleCommand):
                controller_usage[command.controllerId] += 1
            valid[role_id] = command

        # One controller can operate only one weapon and cannot also execute a
        # direct character command in the same round.
        conflicting_controllers = {c for c, count in controller_usage.items() if count > 1}
        if conflicting_controllers:
            for role_id, command in tuple(valid.items()):
                if isinstance(command, AttackRoleCommand) and command.controllerId in conflicting_controllers:
                    valid.pop(role_id, None)
                    rejected.append(role_id)
        controller_ids = {c.controllerId for c in valid.values() if isinstance(c, AttackRoleCommand)}
        for controller_id in controller_ids:
            if controller_id in valid:
                valid.pop(controller_id, None)
                rejected.append(controller_id)

        # Simultaneous own-role movement: same-target contention and direct
        # position swaps both guarantee a collision, so suppress all involved
        # moves before they reach the server.
        self._remove_own_move_conflicts(valid, rejected, own_characters)

        if response.prompt and not llm_call_allowed:
            top.append(FinalValidationIssue("llm_budget_exhausted", "prompt suppressed because the normal daily LLM budget is exhausted"))
        if response.executeCmd and not state.phase_task.strip():
            top.append(FinalValidationIssue("execute_cmd_outside_task", "executeCmd is only legal while a task is active"))

        return FinalValidationResult(
            valid_commands=valid,
            rejected_roles=tuple(dict.fromkeys(rejected)),
            top_level_issues=tuple(top),
        )

    def _validate_command(self, *, state, role_id, command, own_characters, own_buildings, world_memory=None, feedback_memory=None):
        if role_id not in own_characters and role_id not in own_buildings:
            return FinalValidationIssue("unknown_role", "roleCommandMap key is not an own role/building", role_id)
        for pos in self._positions(command):
            if not (0 <= pos.x < state.map_width and 0 <= pos.y < state.map_height):
                return FinalValidationIssue("target_out_of_map", "targetPos lies outside current map bounds", role_id)

        actor = own_characters.get(role_id)
        building = own_buildings.get(role_id)

        if isinstance(command, MoveRoleCommand):
            if actor is None:
                return FinalValidationIssue("move_requires_character", "move must be issued to worker/pioneer", role_id)
            target = command.targetPos[0]
            if not is_adjacent8(actor.position, (target.x, target.y)):
                return FinalValidationIssue("move_step_not_adjacent", "a role may move exactly one of the surrounding 8 cells", role_id)
            if feedback_memory is not None and feedback_memory.is_move_retry_blocked(role_id, target.x, target.y, state.round_id):
                return FinalValidationIssue("repeat_failed_move_retry", "recently failed MOVE target is under team-wide temporary retry guard", role_id)
            traversability = self._traversability(state, world_memory, feedback_memory)
            if not traversability.is_walkable(target.x, target.y):
                return FinalValidationIssue("move_target_blocked", f"move target is a known blocker: {traversability.block_reason(target.x, target.y)}", role_id)
            if state.phase == "night" and actor.role == "worker":
                threat = RobotThreatField(state, None, RobotThreatConfig())
                if max(threat.risk(Position(target.x, target.y), eta) for eta in (0, 1)) >= 1.0:
                    return FinalValidationIssue("unsafe_night_worker_move", "worker move enters observed/predicted robot attack zone", role_id)
            # TaskPoint exit is legal and intentionally permitted. The server ends
            # the active self-evolution task as a gameplay consequence; this is
            # not a malformed instruction and therefore must not be blocked by
            # FinalResponseValidator.

        elif isinstance(command, AttackRoleCommand):
            if state.phase != "night":
                return FinalValidationIssue("attack_only_at_night", "attack is illegal during day", role_id)
            if building is None or building.building_type not in WEAPON_TYPES:
                return FinalValidationIssue("attack_requires_weapon", "attack command key must be an own weapon id", role_id)
            controller = own_characters.get(command.controllerId)
            if controller is None or controller.hp <= 0:
                return FinalValidationIssue("invalid_controller", "controllerId must be a living own character", role_id)
            if not is_adjacent8(controller.position, building.position):
                return FinalValidationIssue("controller_not_adjacent", "weapon controller must stand within one cell of the weapon", role_id)
            expected = 1 if building.building_type == "railgun" else max(1, int(building.level or 1))
            if len(command.targetPos) != expected:
                return FinalValidationIssue("wrong_attack_target_count", f"{building.building_type} level {building.level or 1} requires {expected} targetPos entries", role_id)
            if len({(p.x, p.y) for p in command.targetPos}) != len(command.targetPos):
                return FinalValidationIssue("duplicate_attack_targets", "multi-target attack positions must be distinct", role_id)
            if building.building_type == "rocket" and building.cooldown_remaining > 0:
                return FinalValidationIssue("rocket_on_cooldown", "rocket cooldown is not zero", role_id)
            for target in command.targetPos:
                if not self._weapon_target_in_range(state, building, target):
                    return FinalValidationIssue("attack_target_out_of_range", "attack target exceeds current weapon range", role_id)
            if building.building_type == "gatling" and any(
                not angle_within_90(building.position, a, b)
                for a, b in combinations(command.targetPos, 2)
            ):
                return FinalValidationIssue("gatling_cone_violation", "all gatling targets must lie within one 90-degree cone", role_id)

        elif isinstance(command, BuildRoleCommand):
            if actor is None or actor.role != "worker":
                return FinalValidationIssue("build_requires_worker", "build is a worker action", role_id)
            if state.phase != "day":
                return FinalValidationIssue("build_only_during_day", "build is only legal during day", role_id)
            target = command.targetPos[0]
            if not is_adjacent8(actor.position, (target.x, target.y)):
                return FinalValidationIssue("build_target_not_adjacent", "build target must be within one of the worker's 8 surrounding cells", role_id)
            name = command.name.lower()
            rule = building_rule(name)
            if rule is None or name == "station":
                return FinalValidationIssue("unknown_building", "unsupported build type", role_id)
            if not self._build_area_policy.permits(
                building_name=name,
                target=(target.x, target.y),
                state=state,
            ):
                return FinalValidationIssue(
                    "build_area_unverified",
                    "build target is not in a verified blue/yellow build area",
                    role_id,
                )
            inventory = self._inventory(actor)
            if any(inventory[item] < amount for item, amount in rule.build_items):
                return FinalValidationIssue("missing_build_material", "worker lacks required build material", role_id)
            if state.gold_self < rule.build_gold_cost:
                return FinalValidationIssue("insufficient_build_gold", "not enough gold for weapon construction", role_id)
            own = [b for b in state.buildings if b.owner == "self"]
            existing = next((b for b in own if b.position.x == target.x and b.position.y == target.y), None)
            if name in WEAPON_TYPES:
                replacing = existing is not None and existing.building_type in WEAPON_TYPES
                if sum(1 for b in own if b.building_type in WEAPON_TYPES) >= 3 and not replacing:
                    return FinalValidationIssue("weapon_limit", "at most three weapon buildings may exist simultaneously", role_id)
                if existing is not None and not replacing:
                    return FinalValidationIssue("build_target_occupied", "weapon may only overwrite an existing weapon, not another object", role_id)
                if existing is None and not self._traversability(state, world_memory, feedback_memory).is_walkable(target.x, target.y):
                    return FinalValidationIssue("build_target_blocked", "build target must be empty unless replacing an own weapon", role_id)
            elif name == "wall":
                if sum(1 for b in own if b.building_type == "wall") >= 20:
                    return FinalValidationIssue("wall_limit", "at most 20 walls may exist simultaneously", role_id)
                if not self._traversability(state, world_memory, feedback_memory).is_walkable(target.x, target.y):
                    return FinalValidationIssue("build_target_blocked", "wall target must be an empty cell", role_id)

        elif isinstance(command, RemoveRoleCommand):
            if actor is None or actor.role != "worker":
                return FinalValidationIssue("remove_requires_worker", "remove is a worker action", role_id)
            target = command.targetPos[0]
            if not is_adjacent8(actor.position, (target.x, target.y)):
                return FinalValidationIssue("remove_target_not_adjacent", "wall removal target must be within one cell", role_id)
            if not any(b.owner == "self" and b.building_type == "wall" and b.position.x == target.x and b.position.y == target.y for b in state.buildings):
                return FinalValidationIssue("remove_target_not_own_wall", "remove target must be a known own wall", role_id)

        elif isinstance(command, CollectRoleCommand):
            if actor is None or actor.role != "worker":
                return FinalValidationIssue("collect_requires_worker", "collect is a worker action", role_id)
            if state.phase not in {"day", "night"}:
                return FinalValidationIssue("collect_invalid_phase", "resource collection requires day or night phase", role_id)
            target = command.targetPos[0]
            if state.map_snapshot_complete and not any(r.active and r.position.x == target.x and r.position.y == target.y for r in state.resources):
                return FinalValidationIssue("collect_target_not_resource", "collect target must be a current resource zone", role_id)
            if not is_adjacent8(actor.position, (target.x, target.y)):
                return FinalValidationIssue("collect_target_not_adjacent", "worker must stand within one cell of the resource", role_id)
            if state.phase == "night":
                threat = RobotThreatField(state, None, RobotThreatConfig())
                if not threat.safe_for_window(actor.position, start_eta=0, rounds=1, max_risk=0.35):
                    return FinalValidationIssue("unsafe_night_collect", "worker cannot safely remain for collection", role_id)

        elif isinstance(command, AcceptTaskRoleCommand):
            if actor is None or actor.role != "pioneer":
                return FinalValidationIssue("accept_task_requires_pioneer", "self-evolution task must be accepted by pioneer", role_id)
            if state.phase_task.strip():
                return FinalValidationIssue("task_already_active", "cannot accept another task while phaseTask is active", role_id)
            valid_task_zones = available_task_zone_positions(state)
            if not valid_task_zones:
                return FinalValidationIssue("no_available_task", "no valid self-evolution task is currently available", role_id)
            if not any(is_adjacent8(actor.position, p) for p in valid_task_zones):
                return FinalValidationIssue("no_available_task_adjacent", "pioneer must stand within one cell of an own TaskPoint", role_id)

        elif isinstance(command, SubmitAnswerRoleCommand):
            if actor is None or actor.role != "pioneer":
                return FinalValidationIssue("submit_answer_requires_pioneer", "task answers are submitted by pioneer", role_id)
            if not state.phase_task.strip():
                return FinalValidationIssue("no_active_task", "submitAnswer requires an active task", role_id)

        elif isinstance(command, SummonTreasureRoleCommand):
            if actor is None or actor.role != "pioneer":
                return FinalValidationIssue("summon_requires_pioneer", "summonTreasure requires pioneer", role_id)
            target = command.targetPos[0]
            if not is_adjacent8(actor.position, (target.x, target.y)):
                return FinalValidationIssue("treasure_target_not_adjacent", "treasure target must be within one cell of pioneer", role_id)
            inventory = self._inventory(actor)
            required = Counter(item.lower() for item in command.item)
            if any(inventory[name] < count for name, count in required.items()):
                return FinalValidationIssue("treasure_item_missing", "sacrifice items must exist in pioneer backpack", role_id)

        elif isinstance(command, SellRoleCommand):
            if actor is None:
                return FinalValidationIssue("sell_requires_character", "sell must be issued to a character", role_id)
            if not self._near_zone(state, actor.position, "vendor"):
                return FinalValidationIssue("seller_not_near_vendor", "sell requires standing within one cell of vendor", role_id)
            inventory = self._inventory(actor)
            if command.name.lower() not in state.market_prices or inventory.get(command.name.lower(), 0) < command.num:
                return FinalValidationIssue("invalid_sell_inventory", "seller lacks requested mineral or mineral is not traded", role_id)

        elif isinstance(command, BuyRoleCommand):
            if actor is None:
                return FinalValidationIssue("buy_requires_character", "buy must be issued to a character", role_id)
            if not self._near_zone(state, actor.position, "weaponShop"):
                return FinalValidationIssue("buyer_not_near_shop", "buy requires standing within one cell of weapon shop", role_id)
            price = self._shop_price(state, command.name)
            if price is None:
                return FinalValidationIssue("unknown_shop_item", "buy item is not in current weaponShopList", role_id)
            if state.gold_self < price * command.num:
                return FinalValidationIssue("insufficient_gold", "not enough gold for requested purchase", role_id)

        elif isinstance(command, UseRoleCommand):
            if actor is None:
                return FinalValidationIssue("use_requires_character", "use must be issued to a character", role_id)
            issue = self._validate_use(state, actor, command, role_id)
            if issue is not None:
                return issue

        elif isinstance(command, DropRoleCommand):
            if actor is None:
                return FinalValidationIssue("drop_requires_character", "drop must be issued to a character", role_id)
            if self._inventory(actor).get(command.name.lower(), 0) <= 0:
                return FinalValidationIssue("drop_item_missing", "drop item is not present in backpack", role_id)

        return None

    def _validate_use(self, state, actor, command, role_id):
        inventory = self._inventory(actor)
        name = command.name
        if inventory.get(name.lower(), 0) <= 0:
            return FinalValidationIssue("item_not_in_backpack", "used item is not present in backpack", role_id)
        positions = tuple(command.targetPos or ())
        if name == "Medicine":
            if positions:
                return FinalValidationIssue("medicine_has_target", "Medicine does not require targetPos", role_id)
            return None
        if name in {"DizzyWeapon", "Bomb"}:
            if len(positions) != 1:
                return FinalValidationIssue("use_target_required", "DizzyWeapon/Bomb require one targetPos", role_id)
            return None
        if name in {"SmallRobotSummonOrder", "MiddleRobotSummonOrder", "LargeRobotSummonOrder", "BossRobotSummonOrder"}:
            if positions:
                return FinalValidationIssue("summon_order_has_target", "robot summon orders do not require targetPos", role_id)
            return None
        if len(positions) != 1:
            return FinalValidationIssue("use_target_required", "repair/upgrade item requires one targetPos", role_id)
        target = positions[0]
        target_building = next((b for b in state.buildings if b.owner == "self" and b.position.x == target.x and b.position.y == target.y), None)
        if target_building is None or not is_adjacent8(actor.position, (target.x, target.y)):
            return FinalValidationIssue("use_target_not_adjacent_building", "repair/upgrade target must be an adjacent own building", role_id)
        if name == "WallFixer":
            if target_building.building_type != "wall":
                return FinalValidationIssue("wallfixer_wrong_target", "WallFixer targets an own wall", role_id)
            return None
        specs = {
            "WeaponUpgradeVoucher1": (WEAPON_TYPES, 1),
            "WeaponUpgradeVoucher2": (WEAPON_TYPES, 2),
            "WallUpgradeVoucher1": ({"wall"}, 1),
            "WallUpgradeVoucher2": ({"wall"}, 2),
            "StationUpgradeVoucher1": ({"station"}, 1),
            "StationUpgradeVoucher2": ({"station"}, 2),
        }
        spec = specs.get(name)
        if spec is None:
            return FinalValidationIssue("unsupported_use_item", "task supplies must be used by summonTreasure, not use", role_id)
        types, level = spec
        if target_building.building_type not in types or int(target_building.level or 1) != level:
            return FinalValidationIssue("voucher_wrong_target", "upgrade voucher target type/level does not match", role_id)
        return None

    @staticmethod
    def _remove_own_move_conflicts(valid, rejected, own_characters):
        moves = {rid: cmd for rid, cmd in valid.items() if isinstance(cmd, MoveRoleCommand) and rid in own_characters}
        by_target: dict[tuple[int, int], list[str]] = {}
        for rid, cmd in moves.items():
            pos = cmd.targetPos[0]
            by_target.setdefault((pos.x, pos.y), []).append(rid)
        conflicts = {rid for ids in by_target.values() if len(ids) > 1 for rid in ids}
        for a, cmd_a in moves.items():
            ta = cmd_a.targetPos[0]
            start_a = own_characters[a].position
            for b, cmd_b in moves.items():
                if a >= b:
                    continue
                tb = cmd_b.targetPos[0]
                start_b = own_characters[b].position
                if ta.x == start_b.x and ta.y == start_b.y and tb.x == start_a.x and tb.y == start_a.y:
                    conflicts.update({a, b})
        for rid in conflicts:
            if rid in valid:
                valid.pop(rid, None)
                rejected.append(rid)

    @staticmethod
    def _weapon_target_in_range(state, building, target) -> bool:
        if building.building_type == "rocket" and int(building.level or 1) >= 3:
            return True
        server_range = int(building.attack_range or 0)
        official_range = weapon_attack_range(building.building_type, building.level)
        if official_range is None:
            return True
        effective = int(official_range) if server_range <= 0 else min(server_range, int(official_range))
        return chebyshev_distance(building.position, (target.x, target.y)) <= effective

    @staticmethod
    def _traversability(state, world_memory, feedback_memory):
        if world_memory is not None:
            return TraversabilityMap.from_state_and_memory(state, world_memory, feedback_memory)
        return TraversabilityMap.from_state(state)

    @staticmethod
    def _inventory(actor):
        return {item.item_type.lower(): item.amount for item in actor.inventory}

    @staticmethod
    def _positions(command):
        return tuple(getattr(command, "targetPos", None) or ())

    @staticmethod
    def _near_zone(state, position, zone_type):
        return any(zone.zone_type == zone_type and is_adjacent8(position, zone.position) for zone in state.neutral_zones)


    @staticmethod
    def _shop_price(state, name):
        if name in state.weapon_shop:
            return float(state.weapon_shop[name])
        lname = name.lower()
        for key, value in state.weapon_shop.items():
            if key.lower() == lname:
                return float(value)
        return None
