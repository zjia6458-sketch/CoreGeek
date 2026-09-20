"""Keep a worker's economic transaction stable after safety/legality checks."""
from fortress_agent.domain.action import (
    GatherAction,
    GoalApproachAction,
    ResourceApproachAction,
    SellAction,
)
from fortress_agent.game_rules.economy import vendor_trip_due


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
            return 3
        if isinstance(action, GoalApproachAction) and action.goal_kind == "vendor":
            return 2
    if isinstance(action, (GatherAction, ResourceApproachAction)) and str(action.resource_id) == committed:
        return 1
    return 0
