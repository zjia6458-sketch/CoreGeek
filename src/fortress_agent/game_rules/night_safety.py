"""夜间 Worker 采矿安全门控。

这里的安全判断发生在 Candidate 之前/之内，而不是靠 Utility 降权，因此高价值矿
不能覆盖生存硬约束。RobotThreatField 是保守预测，不声称复刻服务器机器人寻路器。
"""
from __future__ import annotations

from dataclasses import dataclass

from fortress_agent.domain.state import Position
from fortress_agent.world.safe_pathfinding import RobotThreatConfig, RobotThreatField, SafePathPlanner
from fortress_agent.world.traversability import TraversabilityMap
from fortress_agent.world.pathfinding import NavigationPolicy, PathResult


@dataclass(frozen=True, slots=True)
class NightResourceRoute:
    resource_id: str
    access_cell: Position
    path: PathResult
    arrival_risk: float
    escape_path: PathResult
    safety_score: float


def _threshold(ctx, key: str, default: float) -> float:
    return float(ctx.policy_state.thresholds.get(key, default))


def _parameter(ctx, key: str, default: float) -> float:
    return float(ctx.policy_state.parameters.get(key, default))


def threat_field(ctx) -> RobotThreatField:
    return RobotThreatField(
        ctx.state,
        ctx.robot_trajectory,
        RobotThreatConfig(
            prediction_horizon=int(_threshold(ctx, "night_robot_prediction_horizon", 12.0)),
            observed_heading_steps=int(_threshold(ctx, "night_robot_observed_heading_steps", 3.0)),
            hard_safety_margin=int(_threshold(ctx, "night_robot_hard_safety_margin", 1.0)),
            soft_safety_margin=int(_threshold(ctx, "night_robot_soft_safety_margin", 3.0)),
        ),
    )


def is_edge_resource(ctx, resource) -> bool:
    margin = max(0, int(_threshold(ctx, "night_edge_mining_margin_cells", 5.0)))
    x, y = int(resource.x), int(resource.y)
    edge_distance = min(x, y, ctx.state.map_width - 1 - x, ctx.state.map_height - 1 - y)
    return edge_distance <= margin


def _edge_sanctuary_cells(ctx, traversability: TraversabilityMap, field: RobotThreatField, *, eta: int) -> tuple[Position, ...]:
    margin = max(1, int(_threshold(ctx, "night_edge_mining_margin_cells", 5.0)))
    max_risk = _parameter(ctx, "night_escape_max_risk", 0.45)
    cells: list[Position] = []
    for y in range(ctx.state.map_height):
        for x in range(ctx.state.map_width):
            if min(x, y, ctx.state.map_width - 1 - x, ctx.state.map_height - 1 - y) > margin:
                continue
            if not traversability.is_walkable(x, y):
                continue
            pos = Position(x, y)
            if field.risk(pos, eta) <= max_risk:
                cells.append(pos)
    # Keep target set bounded and deterministic; corners / closest outer cells are enough
    # for escape feasibility while avoiding a huge heuristic set.
    return tuple(sorted(cells, key=lambda p: (p.x, p.y))[:256])


def night_resource_route(ctx, actor, resource) -> NightResourceRoute | None:
    if ctx.state.phase.lower() != "night" or actor.role.lower() != "worker":
        return None
    if actor.max_hp:
        hp_ratio = actor.hp / max(1, actor.max_hp)
        if hp_ratio < _threshold(ctx, "night_worker_min_hp_ratio", 0.55):
            return None
    if not is_edge_resource(ctx, resource):
        return None

    traversability = TraversabilityMap.from_state_and_memory(
        ctx.state, ctx.world_memory, ctx.feedback_memory
    )
    access = traversability.resource_access_cells(resource)
    if not access:
        return None

    field = threat_field(ctx)
    planner = SafePathPlanner(
        width=ctx.state.map_width,
        height=ctx.state.map_height,
        threat=field,
        threat_weight=_parameter(ctx, "night_threat_path_weight", 6.0),
        hard_risk_threshold=_parameter(ctx, "night_hard_risk_threshold", 1.0),
        max_steps=int(_threshold(ctx, "night_safe_path_max_steps", 64.0)),
    )
    path = planner.find_path_to_any(
        ctx.world_memory,
        actor.position,
        access,
        traversability=traversability,
        policy=NavigationPolicy.ALLOW_UNKNOWN,
        deadline=ctx.deadline,
    )
    if not path.found:
        return None
    arrival = path.path[-1]
    eta = max(0, path.steps)
    max_resource_risk = _parameter(ctx, "night_resource_max_risk", 0.35)
    arrival_risk = field.risk(arrival, eta)
    if arrival_risk > max_resource_risk:
        return None
    hold = max(0, int(_threshold(ctx, "night_resource_min_safe_hold_rounds", 3.0)))
    if not field.safe_for_window(arrival, start_eta=eta, rounds=hold, max_risk=max_resource_risk):
        return None

    escape_start_eta = eta + hold
    sanctuary = _edge_sanctuary_cells(ctx, traversability, field, eta=escape_start_eta)
    if not sanctuary:
        return None
    escape = planner.find_path_to_any(
        ctx.world_memory,
        arrival,
        sanctuary,
        traversability=traversability,
        policy=NavigationPolicy.ALLOW_UNKNOWN,
        deadline=ctx.deadline,
        start_eta=escape_start_eta,
    )
    if not escape.found:
        return None

    # 0..1-ish score for ranking among already-safe routes.
    safety_score = max(0.0, 1.0 - max(arrival_risk, _parameter(ctx, "night_escape_max_risk", 0.45) * 0.25))
    return NightResourceRoute(
        resource_id=str(resource.resource_id),
        access_cell=arrival,
        path=path,
        arrival_risk=arrival_risk,
        escape_path=escape,
        safety_score=safety_score,
    )


def night_gather_is_safe(ctx, actor, resource) -> bool:
    """Check one stationary collect turn plus post-collect escape feasibility."""
    if ctx.state.phase.lower() != "night":
        return True
    if not is_edge_resource(ctx, resource):
        return False
    field = threat_field(ctx)
    max_resource_risk = _parameter(ctx, "night_resource_max_risk", 0.35)
    if field.risk(actor.position, 1) > max_resource_risk:
        return False
    traversability = TraversabilityMap.from_state_and_memory(
        ctx.state, ctx.world_memory, ctx.feedback_memory
    )
    sanctuary = _edge_sanctuary_cells(ctx, traversability, field, eta=1)
    if not sanctuary:
        return False
    planner = SafePathPlanner(
        width=ctx.state.map_width,
        height=ctx.state.map_height,
        threat=field,
        threat_weight=_parameter(ctx, "night_threat_path_weight", 6.0),
        hard_risk_threshold=_parameter(ctx, "night_hard_risk_threshold", 1.0),
        max_steps=int(_threshold(ctx, "night_safe_path_max_steps", 64.0)),
    )
    escape = planner.find_path_to_any(
        ctx.world_memory,
        actor.position,
        sanctuary,
        traversability=traversability,
        deadline=ctx.deadline,
        start_eta=1,
    )
    return escape.found


def night_retreat_step(ctx, actor) -> Position | None:
    """Return first Safe-A* step toward a low-risk edge sanctuary."""
    if ctx.state.phase.lower() != "night" or actor.role.lower() != "worker":
        return None
    traversability = TraversabilityMap.from_state_and_memory(
        ctx.state, ctx.world_memory, ctx.feedback_memory
    )
    field = threat_field(ctx)
    sanctuary = _edge_sanctuary_cells(ctx, traversability, field, eta=0)
    if not sanctuary:
        return None
    planner = SafePathPlanner(
        width=ctx.state.map_width,
        height=ctx.state.map_height,
        threat=field,
        threat_weight=_parameter(ctx, "night_threat_path_weight", 6.0),
        hard_risk_threshold=_parameter(ctx, "night_hard_risk_threshold", 1.0),
        max_steps=int(_threshold(ctx, "night_safe_path_max_steps", 64.0)),
    )
    result = planner.find_path_to_any(
        ctx.world_memory,
        actor.position,
        sanctuary,
        traversability=traversability,
        deadline=ctx.deadline,
    )
    if not result.found or result.steps < 1:
        return None
    return result.path[1]
