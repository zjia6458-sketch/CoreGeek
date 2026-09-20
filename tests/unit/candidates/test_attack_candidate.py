from types import MappingProxyType

from fortress_agent.candidates.basic import AttackCandidateGenerator
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.memory.world import WorldMemory
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.strategy import StrategyProfile
from fortress_agent.protocol.codec import GameProtocolCodec


class Deadline:
    def remaining(self):
        return 10
    def expired(self):
        return False


def test_night_attack_candidates_use_real_weapon_and_controller_ids():
    parsed = GameProtocolCodec().parse_state({
        "roundNo": 85,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": [],
        },
        "teamOur": {
            "type": "challenger",
            "teamId": "x",
            "teamName": "x",
            "goldNum": 0,
            "totalScore": 0,
            "playerTasks": [],
            "roles": [
                {
                    "id": 10010,
                    "pos": {"x": 8, "y": 24},
                    "roleType": "worker",
                    "health": 220,
                    "attackPower": 0,
                    "attackRange": 0,
                    "backPackCapability": 100,
                    "backpack": [],
                },
                {
                    "id": 10020,
                    "pos": {"x": 9, "y": 24},
                    "roleType": "gatling",
                    "health": 1000,
                    "attackPower": 10,
                    "attackRange": 4,
                    "level": 1,
                    "backPackCapability": 0,
                    "backpack": [],
                },
            ],
        },
        "teamEnemy": {"roles": []},
        "robot": {
            "roles": [{
                "id": 30001,
                "pos": {"x": 9, "y": 21},
                "roleType": "smallRobot",
                "health": 40,
                "abnormalState": "",
                "targetTeam": "challenger",
            }]
        },
        "errors": [],
    })
    assert parsed.ok

    ctx = PolicyContext(
        state=parsed.value,
        world_memory=WorldMemory().view(),
        policy_state=PolicyState.create(),
        deadline=Deadline(),
        features=MappingProxyType({}),
    )

    actions = AttackCandidateGenerator().generate(
        ctx,
        StrategyProfile(
            strategy_id="defense",
            candidate_tags=frozenset({"defense"}),
        ),
    )

    assert actions
    assert actions[0].actor_id == 10020
    assert actions[0].controller_id == 10010
    assert actions[0].targets[0].x == 9
    assert actions[0].targets[0].y == 21
