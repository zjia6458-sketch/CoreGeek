"""经济职责、资源保留与夜前建设节奏的纯策略辅助函数。

本模块只包含“我方策略软规则”，所有阈值均从 ``PolicyState`` 读取；官方硬规则
（70 回合白天、20 墙上限等）仍来自 ``game_rules.constants``。
"""
from __future__ import annotations

from collections import Counter
import math

from fortress_agent.config.tuning import DEFAULT_PARAMETERS, DEFAULT_THRESHOLDS
from fortress_agent.game_rules.catalog import DEFAULT_FIRST_WEAPON_TYPE, WEAPON_TYPES
from fortress_agent.game_rules.constants import DAY_TURNS, WALL_LIMIT
from fortress_agent.game_rules.build_area import (
    wall_blueprint_cells, wall_blueprint_missing_count, wall_blueprint_complete,
)
from fortress_agent.game_rules.geometry import is_adjacent8


def _threshold(policy_state, key: str) -> float:
    return float(policy_state.thresholds.get(key, DEFAULT_THRESHOLDS[key]))


def _parameter(policy_state, key: str) -> float:
    return float(policy_state.parameters.get(key, DEFAULT_PARAMETERS[key]))


def worker_ids(state) -> tuple[str, ...]:
    return tuple(
        str(actor.actor_id)
        for actor in sorted(
            (a for a in state.characters if a.role == "worker" and a.hp > 0),
            key=lambda a: str(a.actor_id),
        )
    )


def primary_builder_id(state) -> str | None:
    ids = worker_ids(state)
    return ids[0] if ids else None


def wall_count(state) -> int:
    return sum(1 for b in state.buildings if b.owner == "self" and b.building_type == "wall")


def weapon_count(state) -> int:
    return sum(1 for b in state.buildings if b.owner == "self" and b.building_type in WEAPON_TYPES)


def next_weapon_build_type(state) -> str | None:
    """Fill three weapon slots with early-game Rockets before upgrading.

    Existing mixed defenses count toward the target and are never replaced.
    """
    return DEFAULT_FIRST_WEAPON_TYPE if weapon_count(state) < 3 else None


def inventory_counts(actor) -> Counter[str]:
    return Counter({item.item_type.lower(): item.amount for item in actor.inventory})


def backpack_used(actor) -> int:
    return sum(item.amount for item in actor.inventory)


def backpack_usage_ratio(actor) -> float:
    if not actor.backpack_capacity:
        return 0.0
    return backpack_used(actor) / max(1, actor.backpack_capacity)


def mineral_inventory_amount(actor) -> int:
    inv = inventory_counts(actor)
    return inv["stone"] + inv["iron"] + inv["copper"]


def mineral_inventory_ratio(actor) -> float:
    if not actor.backpack_capacity:
        return 0.0
    return mineral_inventory_amount(actor) / max(1, actor.backpack_capacity)


def nonstone_inventory_amount(actor) -> int:
    """Return immediately sellable construction-independent minerals."""
    inv = inventory_counts(actor)
    return inv["iron"] + inv["copper"]


def nonstone_cash_out_due(state, actor, policy_state) -> bool:
    """Whether a Worker should pause mining and convert ore to gold."""
    amount = nonstone_inventory_amount(actor)
    if amount <= 0:
        return False
    batch = max(1, int(_threshold(policy_state, "nonstone_sell_batch_size")))
    return amount >= batch or backpack_high_watermark_reached(actor, policy_state)


def day_elapsed_rounds(state) -> int:
    if state.phase != "day":
        return DAY_TURNS
    if state.phase_round is not None:
        # 接口中的 phase_round 按比赛实现可能从 0 或 1 开始；这里只用于软策略分段，
        # 因此统一截断在 [0, DAY_TURNS] 即可。
        return max(0, min(DAY_TURNS, int(state.phase_round)))
    remaining = state.turns_until_phase_change
    if remaining is None:
        return 0
    return max(0, min(DAY_TURNS, DAY_TURNS - int(remaining)))


def is_early_day_full_mining(state, policy_state) -> bool:
    if state.phase != "day":
        return False
    return day_elapsed_rounds(state) <= int(_threshold(policy_state, "early_day_full_backpack_rounds"))


def in_wall_build_reserve_window(state, policy_state) -> bool:
    remaining = state.turns_until_phase_change
    return (
        state.phase == "day"
        and remaining is not None
        and remaining <= int(_threshold(policy_state, "wall_build_reserve_rounds"))
    )


def in_mining_emergency_window(state, policy_state) -> bool:
    remaining = state.turns_until_phase_change
    return (
        state.phase == "day"
        and remaining is not None
        and remaining <= int(_threshold(policy_state, "mining_emergency_rounds"))
    )


def backpack_high_watermark_reached(actor, policy_state) -> bool:
    return backpack_usage_ratio(actor) >= _threshold(policy_state, "backpack_high_watermark_ratio")


def near_night_mineral_return_due(state, actor, policy_state) -> bool:
    return (
        in_wall_build_reserve_window(state, policy_state)
        and mineral_inventory_ratio(actor) >= _threshold(policy_state, "near_night_mineral_return_ratio")
    )


def wall_target_for_day(state, policy_state=None) -> int:
    """标准地图以三面墙 Blueprint 的实际格数为目标。

    显式特殊地图没有标准 Station blueprint 时才退回可配置软目标。
    """
    blueprint = wall_blueprint_cells(state)
    if blueprint:
        return len(blueprint)
    if policy_state is None:
        class _P:
            thresholds = {}
        policy_state = _P()
    day = max(1, int(getattr(state, "day", 1) or 1))
    base = int(_threshold(policy_state, "wall_day1_target"))
    step = int(_threshold(policy_state, "wall_target_increment_per_day"))
    maximum = int(_threshold(policy_state, "wall_target_max"))
    return min(maximum, base + step * (day - 1))


def wall_construction_due(state, policy_state=None) -> bool:
    if weapon_count(state) < 3:
        return False
    blueprint = wall_blueprint_cells(state)
    if blueprint:
        return wall_blueprint_missing_count(state) > 0
    return wall_count(state) < wall_target_for_day(state, policy_state)


def wall_return_urgent(state, policy_state=None) -> bool:
    """进入施工预留窗口后，已有材料应尽快返场。"""
    if policy_state is None:
        class _P:
            thresholds = {}
        policy_state = _P()
    return in_wall_build_reserve_window(state, policy_state)


def stone_batch_target(state, actor, policy_state=None) -> int:
    """单个 Worker 的 stone 运输批量。"""
    if policy_state is None:
        class _P:
            thresholds = {}
        policy_state = _P()
    blueprint = wall_blueprint_cells(state)
    remaining = (
        wall_blueprint_missing_count(state)
        if blueprint
        else max(0, wall_target_for_day(state, policy_state) - wall_count(state))
    )
    if remaining <= 0:
        return 0
    if in_mining_emergency_window(state, policy_state):
        return 1
    workers = max(1, len(worker_ids(state)))
    per_worker = max(1, math.ceil(remaining / workers))
    configured = max(1, int(_threshold(policy_state, "stone_batch_size")))
    return min(configured, per_worker)


def reserved_stone(state, actor) -> int:
    """三面墙 Blueprint 未完成时，stone 始终作为战略材料保留。

    Worker-2 从开局就采 stone；即使 Worker-1 尚未完成三座火箭塔，也不应把
    这些石头提前卖掉，否则会破坏“建塔完成后立即落墙”的长期职责。
    """
    blueprint = wall_blueprint_cells(state)
    remaining_walls = (
        wall_blueprint_missing_count(state)
        if blueprint
        else max(0, WALL_LIMIT - wall_count(state))
    )
    return min(inventory_counts(actor)["stone"], remaining_walls)


def sellable_amount(state, actor, mineral: str) -> int:
    amount = inventory_counts(actor)[mineral.lower()]
    if mineral.lower() == "stone":
        blueprint = wall_blueprint_cells(state)
        # 标准比赛有 Station，因此能得到三面墙 Blueprint；只有这种明确存在长期
        # 建设计划的状态才冻结 stone。无 Station 的轻量测试/特殊场景仍允许正常卖出。
        if blueprint and wall_blueprint_missing_count(state) > 0:
            return max(0, amount - reserved_stone(state, actor))
    return amount


def wall_health_ratio(wall) -> float:
    if not wall.max_hp or wall.hp is None:
        return 1.0
    return max(0.0, min(1.0, wall.hp / max(1, wall.max_hp)))


def wall_rebuild_target(state, actor, policy_state):
    """Lowest-health wall worth replacing, when the Worker carries stone."""
    if inventory_counts(actor)["stone"] <= 0:
        return None
    threshold = _threshold(policy_state, "wall_rebuild_hp_ratio")
    candidates = [
        b for b in state.buildings
        if b.owner == "self" and b.building_type == "wall"
        and wall_health_ratio(b) < threshold
    ]
    return min(candidates, key=lambda b: (wall_health_ratio(b), str(b.building_id)), default=None)


def wall_fixer_target(state, actor, policy_state):
    """Lowest damaged wall not better handled by an available rebuild."""
    fixer = _threshold(policy_state, "wall_fixer_hp_ratio")
    rebuild = _threshold(policy_state, "wall_rebuild_hp_ratio")
    has_rebuild_stone = inventory_counts(actor)["stone"] > 0
    candidates = [
        b for b in state.buildings
        if b.owner == "self" and b.building_type == "wall"
        and wall_health_ratio(b) < fixer
        and (not has_rebuild_stone or wall_health_ratio(b) >= rebuild)
    ]
    return min(candidates, key=lambda b: (wall_health_ratio(b), str(b.building_id)), default=None)


def adjacent_available_resources(ctx, actor):
    return tuple(
        resource
        for resource in ctx.world_memory.available_resources()
        if is_adjacent8(actor.position, (resource.x, resource.y))
    )


def should_hold_current_mine(ctx, actor) -> bool:
    """是否应留在当前矿旁持续 collect，而不是生成普通移动。

    规则优先级：
    1. 紧急窗口：若已在本矿紧急额外采过一次，则必须离开；否则允许再采一次。
    2. 建墙预留窗口且背包矿物达到返场阈值：离开。
    3. 背包已满：离开。
    4. 其余情况：只要当前矿仍存在，就继续采，尽量把当前矿采完。
    """
    resources = adjacent_available_resources(ctx, actor)
    if not resources:
        return False
    if actor.backpack_capacity and backpack_used(actor) >= actor.backpack_capacity:
        return False
    if (
        nonstone_cash_out_due(ctx.state, actor, ctx.policy_state)
        and any(zone.zone_type == "vendor" for zone in ctx.state.neutral_zones)
    ):
        return False
    if near_night_mineral_return_due(ctx.state, actor, ctx.policy_state):
        return False
    if in_mining_emergency_window(ctx.state, ctx.policy_state):
        if ctx.mining_memory is None:
            return True
        return any(
            not ctx.mining_memory.emergency_sample_taken(
                actor.actor_id,
                day=ctx.state.day,
                resource_id=resource.resource_id,
            )
            for resource in resources
        )
    return True


def resource_selection_score(ctx, actor, resource, *, distance: int) -> tuple[float, dict[str, float], str]:
    """资源预筛选公式。

    默认强调距离而不是售价：
    ``score = w_distance/(distance+1) + market_value*w_value + commitment + wall_bonus``。
    返回分数、各项贡献和人类可读公式，供 HIGH/MEDIUM 日志解释。
    """
    ps = ctx.policy_state
    # 防线完成前：距离优先，尽快拿到 stone；三面墙完整后：切换到赚钱/升级阶段，
    # 使用另一组“价值优先”的可配置权重。
    if weapon_count(ctx.state) >= 3 and wall_blueprint_complete(ctx.state):
        w_distance = _parameter(ps, "post_wall_resource_distance_weight")
        w_value = _parameter(ps, "post_wall_resource_market_value_weight")
    else:
        w_distance = _parameter(ps, "resource_distance_weight")
        w_value = _parameter(ps, "resource_market_value_weight")
    unit_value = float(ctx.state.market_prices.get(resource.resource_type, 1.0))
    distance_term = w_distance / max(1.0, float(distance) + 1.0)
    value_term = unit_value * w_value
    commitment = 0.0
    if ctx.mining_memory is not None and ctx.mining_memory.committed_resource(actor.actor_id) == str(resource.resource_id):
        commitment = _parameter(ps, "resource_commitment_bonus")

    wall_bonus = 0.0
    if wall_construction_due(ctx.state, ps) and resource.resource_type.lower() == "stone":
        wall_bonus += _parameter(ps, "resource_wall_stone_bonus")
        if str(actor.actor_id) == primary_builder_id(ctx.state):
            wall_bonus += _parameter(ps, "resource_builder_stone_bonus")
    elif (
        str(actor.actor_id) == primary_builder_id(ctx.state)
        and weapon_count(ctx.state) >= 3
        and wall_construction_due(ctx.state, ps)
        and resource.resource_type.lower() != "stone"
    ):
        wall_bonus -= _parameter(ps, "resource_builder_nonstone_penalty")

    total = distance_term + value_term + commitment + wall_bonus
    components = {
        "distance_term": distance_term,
        "market_value_term": value_term,
        "commitment_bonus": commitment,
        "wall_bonus": wall_bonus,
    }
    formula = (
        f"resource_score={w_distance:.3f}/(distance({distance})+1)"
        f"+market_value({unit_value:.3f})*{w_value:.3f}"
        f"+commitment({commitment:.3f})+wall({wall_bonus:.3f})={total:.3f}"
    )
    return total, components, formula
