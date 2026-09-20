from types import MappingProxyType

from fortress_agent.candidates.basic import (
    ExplorationCandidateGenerator,
    GatherCandidateGenerator,
    MoveCandidateGenerator,
    ResourceApproachCandidateGenerator,
)
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.domain.state import Position
from fortress_agent.memory.world import WorldMemory
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.strategy import StrategyProfile
from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.safety.emergency import BasicEmergencyPolicy
from fortress_agent.world.pathfinding import AStarPathfinder
from fortress_agent.world.traversability import TraversabilityMap


class Deadline:
    def remaining(self):
        return 10.0
    def expired(self):
        return False


def make_ctx(worker=(5, 23), stone=(4, 24)):
    result = GameProtocolCodec().parse_state({
        "roundNo": 10,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": [
                {"neutralType": "stone", "pos": {"x": stone[0], "y": stone[1]}},
            ],
        },
        "teamOur": {
            "type": "challenger",
            "teamId": "x",
            "teamName": "x",
            "goldNum": 0,
            "totalScore": 0,
            "playerTasks": [],
            "roles": [{
                "id": 10010,
                "pos": {"x": worker[0], "y": worker[1]},
                "roleType": "worker",
                "health": 220,
                "attackPower": 0,
                "attackRange": 0,
                "backPackCapability": 100,
                "backpack": [],
            }],
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": []},
        "errors": [],
    })
    assert result.ok, result

    memory = WorldMemory()
    memory.resources.discover(
        resource_id=f"zone:stone:{stone[0]}:{stone[1]}",
        resource_type="stone",
        x=stone[0],
        y=stone[1],
        amount=None,
        round_id=10,
    )

    return PolicyContext(
        state=result.value,
        world_memory=memory.view(),
        policy_state=PolicyState.create(),
        deadline=Deadline(),
        features=MappingProxyType({}),
    )


def test_worker_adjacent_to_active_resource_holds_position_instead_of_wandering():
    ctx = make_ctx(worker=(4, 23), stone=(4, 24))
    strategy = StrategyProfile(
        strategy_id="test",
        candidate_tags=frozenset({"move", "explore"}),
    )

    # 新采矿契约：已经到矿旁时尽量连续采完当前矿，普通 MOVE/Explore 不再
    # 与 collect 竞争；资源格本身仍由 Traversability 永久禁止站入。
    actions = (
        MoveCandidateGenerator().generate(ctx, strategy)
        + ExplorationCandidateGenerator().generate(ctx, strategy)
    )
    assert actions == ()
    gather_strategy = StrategyProfile(strategy_id="economy", candidate_tags=frozenset({"gather"}))
    gathers = GatherCandidateGenerator().generate(ctx, gather_strategy)
    assert len(gathers) == 1


def test_collect_is_generated_only_from_adjacent_walkable_cell():
    adjacent = make_ctx(worker=(4, 23), stone=(4, 24))
    far = make_ctx(worker=(6, 23), stone=(4, 24))
    strategy = StrategyProfile(
        strategy_id="economy",
        candidate_tags=frozenset({"gather"}),
    )

    assert len(GatherCandidateGenerator().generate(adjacent, strategy)) == 1
    assert GatherCandidateGenerator().generate(far, strategy) == ()


def test_resource_approach_targets_access_cell_not_resource_cell():
    ctx = make_ctx(worker=(6, 23), stone=(4, 24))
    strategy = StrategyProfile(
        strategy_id="economy",
        candidate_tags=frozenset({"gather"}),
    )

    actions = ResourceApproachCandidateGenerator().generate(ctx, strategy)
    assert actions
    assert all((action.x, action.y) != (4, 24) for action in actions)
    assert all(max(abs(action.x - 4), abs(action.y - 24)) == 1 for action in actions)


def test_pathfinder_routes_around_resource_cell():
    ctx = make_ctx(worker=(4, 23), stone=(4, 24))
    traversal = TraversabilityMap.from_state_and_memory(
        ctx.state,
        ctx.world_memory,
    )
    result = AStarPathfinder(width=41, height=32).find_path(
        ctx.world_memory,
        Position(4, 23),
        Position(4, 25),
        traversability=traversal,
    )

    assert result.found
    assert Position(4, 24) not in result.path


def test_emergency_policy_never_moves_onto_resource_cell():
    ctx = make_ctx(worker=(4, 23), stone=(4, 24))
    action, _ = BasicEmergencyPolicy().select(ctx)

    # Because the resource is adjacent, emergency should collect rather than
    # move. Most importantly it must never emit move(4,24).
    assert action.action_type == "gather"
