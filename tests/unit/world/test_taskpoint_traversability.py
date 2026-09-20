from types import MappingProxyType

from fortress_agent.candidates.business import AcceptTaskCandidateGenerator
from fortress_agent.candidates.navigation import TaskApproachCandidateGenerator
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.memory.feedback import RuntimeFeedbackMemory
from fortress_agent.memory.world import WorldMemory
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.strategy import StrategyProfile
from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.world.traversability import TraversabilityMap


class Deadline:
    def remaining(self): return 10.0
    def expired(self): return False


def state(pioneer=(23, 13)):
    parsed = GameProtocolCodec().parse_state({
        "roundNo": 15,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": [
                {
                    "neutralType": "defenderTaskPoint1",
                    "pos": {"x": 23, "y": 14},
                },
            ],
        },
        "teamOur": {
            "type": "defender",
            "teamId": "4737",
            "teamName": "B",
            "goldNum": 0,
            "totalScore": 0,
            "playerTasks": [{
                "taskType": "自进化类1",
                "taskPosition": {"x": 23, "y": 14},
                "coldDownRounds": 0,
                "scoreReward": 50,
                "goldReward": 30,
                "isValid": True,
                "timeoutRounds": 50,
            }],
            "roles": [{
                "id": 20011,
                "pos": {"x": pioneer[0], "y": pioneer[1]},
                "roleType": "pioneer",
                "health": 200,
                "attackPower": 0,
                "attackRange": 0,
                "backPackCapability": 40,
                "backpack": [],
            }],
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": []},
        "errors": [],
    })
    assert parsed.ok
    return parsed.value


def ctx(pioneer=(23, 13)):
    s = state(pioneer)
    return PolicyContext(
        state=s,
        world_memory=WorldMemory().view(),
        policy_state=PolicyState.create(),
        deadline=Deadline(),
        features=MappingProxyType({}),
        feedback_memory=RuntimeFeedbackMemory().view(),
    )


def test_task_point_is_hard_impassable_terrain():
    t = TraversabilityMap.from_state(state())
    assert not t.is_walkable(23, 14)
    assert t.is_task_cell(23, 14)
    assert t.block_reason(23, 14) == "task_point_cell"


def test_pioneer_adjacent_to_task_point_does_not_generate_move_onto_task_cell():
    context = ctx((23, 13))
    strategy = StrategyProfile(
        strategy_id="llm_explore",
        candidate_tags=frozenset({"task"}),
    )

    approach = TaskApproachCandidateGenerator().generate(context, strategy)
    accept = AcceptTaskCandidateGenerator().generate(context, strategy)

    assert approach == ()
    assert len(accept) == 1
    assert accept[0].actor_id == 20011


def test_pioneer_far_from_task_routes_to_adjacent_access_cell_not_task_tile():
    context = ctx((23, 11))
    strategy = StrategyProfile(
        strategy_id="llm_explore",
        candidate_tags=frozenset({"task"}),
    )

    actions = TaskApproachCandidateGenerator().generate(context, strategy)
    assert actions
    assert all((a.x, a.y) != (23, 14) for a in actions)
