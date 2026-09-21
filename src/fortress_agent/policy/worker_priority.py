"""Keep a worker's economic transaction stable after safety/legality checks."""
from fortress_agent.domain.action import (
    BuyAction,
    GatherAction,
    GoalApproachAction,
    ResourceApproachAction,
    SellAction,
    UseAction,
)
from fortress_agent.game_rules.economy import primary_builder_id, vendor_trip_due
from fortress_agent.game_rules.upgrades import next_upgrade_target


def _planned_upgrade_action(ctx, actor, action) -> bool:
    """Complete the current defense upgrade without being starved by mining."""
    if not isinstance(action, (BuyAction, UseAction, GoalApproachAction)):
        return False
    upgrade = next_upgrade_target(ctx.state)
    if upgrade is None:
        return False
    voucher = upgrade.voucher_name.casefold()
    held = sum(i.amount for i in actor.inventory if i.item_type.casefold() == voucher) > 0
    if held:
        if isinstance(action, UseAction):
            return action.name.casefold() == voucher and action.target == upgrade.position
        return (
            isinstance(action, GoalApproachAction)
            and action.goal_kind == "upgrade_target"
            and str(action.goal_id) == upgrade.building_id
            and (action.goal_x, action.goal_y) == (upgrade.position.x, upgrade.position.y)
        )
    if str(actor.actor_id) != primary_builder_id(ctx.state):
        return False
    price = next((v for k, v in ctx.state.weapon_shop.items() if k.casefold() == voucher), None)
    if price is None or float(price) > ctx.state.gold_self:
        return False
    return (
        isinstance(action, BuyAction) and action.name.casefold() == voucher
        or isinstance(action, GoalApproachAction) and action.goal_kind == "weapon_shop"
    )


def worker_action_priority(ctx, action) -> int:
    actor = next((a for a in ctx.state.characters if str(a.actor_id) == str(action.actor_id)), None)
    if actor is None or actor.role != "worker":
        return 0
    committed = ctx.mining_memory.committed_resource(actor.actor_id) if ctx.mining_memory else None
    if ctx.state.phase == "night":
        if isinstance(action, GoalApproachAction) and action.goal_kind == "night_retreat":
            return 4
        if isinstance(action, (GatherAction, ResourceApproachAction)) and str(action.resource_id) == committed:
            return 3
        if isinstance(action, GatherAction):
            return 2
        if isinstance(action, ResourceApproachAction):
            return 1
        return 0
    if vendor_trip_due(ctx, actor):
        if isinstance(action, SellAction):
            return 4
        if isinstance(action, GoalApproachAction) and action.goal_kind == "vendor":
            return 3
    if ctx.state.phase == "day" and _planned_upgrade_action(ctx, actor, action):
        return 2
    if isinstance(action, (GatherAction, ResourceApproachAction)) and str(action.resource_id) == committed:
        return 1
    return 0
