from dataclasses import replace
from types import SimpleNamespace

import pytest

from fortress_agent.candidates.basic import (
    AttackCandidateGenerator,
    GatherCandidateGenerator,
    MoveCandidateGenerator,
    NightResourceApproachCandidateGenerator,
    ResourceApproachCandidateGenerator,
)
from fortress_agent.candidates.business import BuildCandidateGenerator
from fortress_agent.candidates.navigation import VendorApproachCandidateGenerator
from fortress_agent.domain.action import (
    MoveAction,
    ResourceApproachAction,
)
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.domain.state import (
    BuildingState,
    CharacterState,
    EnemyState,
    GameState,
    InventoryItem,
    NeutralZoneState,
    Position,
)
from fortress_agent.game_rules.build_area import (
    rocket_cluster_plan,
    wall_blueprint_cells,
)
from fortress_agent.game_rules.geometry import is_adjacent8
from fortress_agent.game_rules.night_safety import (
    night_gather_is_safe,
    night_resource_route,
)
from fortress_agent.game_rules.upgrades import next_upgrade_target
from fortress_agent.memory.economy import MiningRuntimeMemory
from fortress_agent.memory.world import WorldMemory
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.legal import BasicLegalActionFilter
from fortress_agent.policy.strategy import StrategyProfile
from fortress_agent.protocol.final_validator import FinalResponseValidator
from fortress_agent.protocol.server_factory import ServerCommandFactory
from fortress_agent.protocol.server_outbound import ServerCommandResponse
from fortress_agent.safety.emergency import (
    BasicEmergencyPolicy,
    EmergencyActionUnavailable,
)
from fortress_agent.world.safe_pathfinding import (
    RobotThreatConfig,
    RobotThreatField,
    SafePathPlanner,
)
from fortress_agent.world.traversability import TraversabilityMap


def game(*, phase="day", cargo=(), pos=None, enemies=(), buildings=(), zones=()):
    pos = pos or Position(5, 5)
    return GameState(
        round_id=10, day=1, phase=phase, phase_round=10, turns_until_phase_change=60,
        score_self=0, score_opponent=0, anomaly_count=0,
        characters=(CharacterState(10, "worker", 220, 220, pos, 100, cargo),),
        enemies=tuple(enemies), buildings=tuple(buildings), resources=(), tasks=(),
        observed_cells=(), news=(), rumors=(), market_prices={"iron": 3, "copper": 5, "stone": 1},
        neutral_zones=tuple(zones), map_width=41, map_height=32,
    )


def building(bid, kind, pos, **kwargs):
    if kind == "station":
        kwargs.setdefault("footprint_width", 2)
        kwargs.setdefault("footprint_height", 2)
        kwargs.setdefault("footprint_anchor", "top_left")
    return BuildingState(bid, kind, pos, 1000, 1000, "self", 0, level=1, **kwargs)


def enemy(pos):
    return EnemyState(80, "smallrobot", 40, 40, 5, 3, 1, pos)


def ctx(state, resources=(), mining=None):
    memory = WorldMemory()
    for rid, kind, x, y in resources:
        memory.resources.discover(resource_id=rid, resource_type=kind, x=x, y=y, amount=10, round_id=state.round_id)
    return PolicyContext(
        state, memory.view(), PolicyState.create(),
        SimpleNamespace(remaining=lambda: 30.0, expired=lambda: False),
        mining_memory=mining.view() if mining else None,
    )


PROFILE = StrategyProfile("test", frozenset({"gather", "build", "sell", "defense"}))


@pytest.mark.parametrize("amount", [1, 2, 3])
def test_small_batches_keep_mining_instead_of_starting_vendor_trip(amount):
    state = game(cargo=(InventoryItem("iron", amount),), zones=(NeutralZoneState("vendor", Position(1, 5)),))
    context = ctx(state, [("mine", "iron", 6, 5)])
    assert GatherCandidateGenerator().generate(context, PROFILE)
    assert VendorApproachCandidateGenerator().generate(context, PROFILE) == ()


def test_vendor_session_survives_partial_sale_and_clears_only_after_observed_empty_cargo():
    vendor = NeutralZoneState("vendor", Position(1, 5))
    state = game(cargo=(InventoryItem("iron", 4), InventoryItem("copper", 1)), zones=(vendor,))
    mining = MiningRuntimeMemory()
    context = ctx(state, [("mine", "iron", 6, 5)], mining)
    action = VendorApproachCandidateGenerator().generate(context, PROFILE)[0]
    mining.record_confirmed_action(state=state, action=action, emergency_rounds=8)
    partial = replace(state, characters=(replace(state.characters[0], inventory=(InventoryItem("copper", 1),)),))
    context = ctx(partial, [("mine", "iron", 6, 5)], mining)
    mining.reconcile(state=partial, world_memory=context.world_memory)
    context = replace(context, mining_memory=mining.view())
    assert GatherCandidateGenerator().generate(context, PROFILE) == ()
    assert ResourceApproachCandidateGenerator().generate(context, PROFILE) == ()
    assert VendorApproachCandidateGenerator().generate(context, PROFILE)
    empty = replace(partial, characters=(replace(partial.characters[0], inventory=()),))
    mining.reconcile(state=empty, world_memory=context.world_memory)
    assert mining.view().vendor_target(10) is None


def test_unreachable_vendor_does_not_send_loaded_worker_back_to_mining_or_random_move():
    state = game(cargo=(InventoryItem("iron", 4),),
        zones=(NeutralZoneState("vendor", Position(1, 1)),),
        buildings=tuple(building(100 + x * 3 + y, "wall", Position(x, y))
                        for x in range(3) for y in range(3) if (x, y) != (1, 1)))
    context = ctx(state, [("mine", "iron", 6, 5)])
    assert VendorApproachCandidateGenerator().generate(context, PROFILE) == ()
    assert GatherCandidateGenerator().generate(context, PROFILE) == ()
    assert MoveCandidateGenerator().generate(context, PROFILE) == ()
    with pytest.raises(EmergencyActionUnavailable):
        BasicEmergencyPolicy().select(context)


def test_long_mining_trip_does_not_switch_to_a_new_mine_on_the_way():
    state = game()
    mining = MiningRuntimeMemory()
    mining.record_confirmed_action(state=state, action=ResourceApproachAction(10, "move", 6, 5, "far"), emergency_rounds=8)
    later = replace(state, round_id=30, characters=(replace(state.characters[0], position=Position(7, 5)),))
    context = ctx(later, [("far", "iron", 15, 5), ("near", "copper", 6, 5)], mining)
    actions = ResourceApproachCandidateGenerator().generate(context, PROFILE)
    assert actions and {a.resource_id for a in actions} == {"far"}


def test_unreachable_committed_mine_releases_target_for_reachable_alternative():
    state = game(zones=tuple(NeutralZoneState("vendor", Position(x, y))
        for x in range(14, 17) for y in range(4, 7) if (x, y) != (15, 5)))
    mining = MiningRuntimeMemory()
    mining.record_confirmed_action(state=state, action=ResourceApproachAction(10, "move", 6, 5, "far"), emergency_rounds=8)
    context = ctx(state, [("far", "iron", 15, 5), ("near", "copper", 5, 9)], mining)
    actions = ResourceApproachCandidateGenerator().generate(context, PROFILE)
    assert actions and {a.resource_id for a in actions} == {"near"}


def test_legacy_rear_wall_upgrades_after_top_and_bottom_even_with_lower_id():
    state = game(buildings=(building(13, "station", Position(9, 22)),))
    plan = rocket_cluster_plan(state)
    towers = tuple(replace(building(40 + i, "rocket", Position(*p)), level=3) for i, p in enumerate(plan.rocket_cells))
    state = replace(state, buildings=(replace(state.buildings[0], level=3), *towers,
        building(1, "wall", Position(7, 21)), building(100, "wall", Position(9, 24))))
    assert next_upgrade_target(state).building_id == "100"


@pytest.mark.parametrize("base", [Position(9, 22), Position(30, 8)])
def test_three_walls_and_three_rockets_share_one_reserved_controller_cell(base):
    state = game(buildings=(building(13, "station", base, footprint_width=2, footprint_height=2),))
    walls = wall_blueprint_cells(state)
    assert len(walls) == 16
    rear_x = min(x for x, _ in walls) if base.x < 20 else max(x for x, _ in walls)
    # Rear endpoints belong to top/bottom; the middle rear passage stays open.
    assert len([p for p in walls if p[0] == rear_x]) == 2
    plan = rocket_cluster_plan(state)
    assert plan and plan.controller not in walls
    assert len(set(plan.rocket_cells)) == 3 and plan.controller not in plan.rocket_cells
    assert all(is_adjacent8(plan.controller, p) for p in plan.rocket_cells)
    state = replace(state, gold_self=75, characters=(replace(state.characters[0], position=Position(*plan.controller)),))
    for i in range(3):
        actions = BuildCandidateGenerator().generate(ctx(state), PROFILE)
        assert actions and all(a.name == "rocket" for a in actions)
        chosen = actions[0]
        state = replace(state, buildings=(*state.buildings, building(40 + i, "rocket", chosen.target)))
        assert rocket_cluster_plan(state).controller == plan.controller
    assert BuildCandidateGenerator().generate(ctx(state), PROFILE) == ()


def test_cluster_avoids_a_static_blocker_at_the_preferred_controller():
    state = game(buildings=(building(13, "station", Position(9, 22), footprint_width=2, footprint_height=2),))
    initial = rocket_cluster_plan(state)
    state = replace(state, neutral_zones=(NeutralZoneState("vendor", Position(*initial.controller)),))
    updated = rocket_cluster_plan(state)
    assert updated and updated.controller != initial.controller
    assert initial.controller not in updated.rocket_cells


def test_observed_robot_zone_stays_dangerous_even_when_forecast_moves_away():
    state = game(phase="night", enemies=(enemy(Position(12, 10)),),
                 buildings=(building(13, "station", Position(30, 25)),))
    field = RobotThreatField(state, None, RobotThreatConfig(prediction_horizon=2))
    assert field.risk(Position(8, 10), 5) == 1.0
    assert field.risk(Position(24, 22), 12) == 1.0  # prediction continues after horizon


def test_safe_path_rejects_unsafe_nearest_goal_and_reaches_alternative_around_obstacles():
    state = game(pos=Position(1, 1), zones=tuple(NeutralZoneState("vendor", Position(2, y)) for y in range(4)))
    context = ctx(state)
    planner = SafePathPlanner(width=41, height=32, threat=RobotThreatField(state, None, RobotThreatConfig()))
    path = planner.find_path_to_any(context.world_memory, Position(1, 1), (Position(1, 2), Position(4, 1)),
        traversability=TraversabilityMap.from_state(state), goal_is_safe=lambda p, eta: p == Position(4, 1))
    assert path.found and path.path[-1] == Position(4, 1)
    assert any(p.y >= 4 for p in path.path)


def test_unsafe_zero_length_goal_is_not_reported_as_safe():
    state = game(pos=Position(5, 5), enemies=(enemy(Position(8, 5)),))
    context = ctx(state)
    planner = SafePathPlanner(width=41, height=32, threat=RobotThreatField(state, None, RobotThreatConfig()), max_steps=2)
    result = planner.find_path_to_any(context.world_memory, state.characters[0].position, (Position(5, 5),),
                                      traversability=TraversabilityMap.from_state(state))
    assert not result.found


@pytest.mark.parametrize("pos", [Position(2, 2), Position(38, 28), Position(20, 16)])
def test_safe_night_mining_allows_both_edges_and_interior(pos):
    state = game(phase="night", pos=pos)
    context = ctx(state, [("mine", "iron", pos.x + 1, pos.y)])
    resource = context.world_memory.resource("mine")
    assert night_gather_is_safe(context, state.characters[0], resource)
    assert night_resource_route(context, state.characters[0], resource) is not None
    assert GatherCandidateGenerator().generate(context, PROFILE)
    assert NightResourceApproachCandidateGenerator().generate(context, PROFILE) == ()


def test_night_emergency_and_final_gate_never_send_worker_into_robot_zone():
    state = game(phase="night", pos=Position(5, 5), enemies=(enemy(Position(8, 5)),))
    context = ctx(state, [("mine", "iron", 6, 5)])
    assert GatherCandidateGenerator().generate(context, PROFILE) == ()
    assert not BasicLegalActionFilter().is_legal(context, MoveAction(10, "move", 6, 6))
    with pytest.raises(EmergencyActionUnavailable):
        BasicEmergencyPolicy().select(context)
    response = ServerCommandResponse(roleCommandMap={"10": ServerCommandFactory.move((6, 6))})
    assert FinalResponseValidator().validate(state=state, response=response).rejected_roles == ("10",)


def test_one_controller_can_rotate_three_rockets_without_moving():
    base = building(13, "station", Position(9, 22), footprint_width=2, footprint_height=2)
    state = game(phase="night", buildings=(base,), enemies=(enemy(Position(12, 20)),))
    plan = rocket_cluster_plan(state)
    towers = tuple(building(40 + i, "rocket", Position(*cell)) for i, cell in enumerate(plan.rocket_cells))
    controller = replace(state.characters[0], role="pioneer", position=Position(*plan.controller))
    state = replace(state, characters=(controller,), buildings=(base, *towers))
    for ready in range(3):
        state = replace(state, buildings=(base, *(replace(t, cooldown_remaining=0 if i == ready else 2)
                                                  for i, t in enumerate(towers))))
        actions = AttackCandidateGenerator().generate(ctx(state), PROFILE)
        assert actions and {a.actor_id for a in actions} == {40 + ready}
        assert {a.controller_id for a in actions} == {10}
