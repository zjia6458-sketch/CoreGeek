"""Opening construction takes precedence over learned utility preferences."""
from fortress_agent.domain.action import BuildAction, GoalApproachAction
from fortress_agent.game_rules.economy import next_weapon_build_type, primary_builder_id


def opening_construction_priority(state, action) -> int:
    """Rank only viable daytime builder actions; legality remains upstream."""
    if state.phase != "day" or str(action.actor_id) != primary_builder_id(state):
        return 0
    desired = next_weapon_build_type(state)
    if desired is None:
        return 0
    if isinstance(action, BuildAction) and action.name.lower() == desired:
        return 2
    if isinstance(action, GoalApproachAction) and action.goal_kind == "weapon_build":
        return 1
    return 0
