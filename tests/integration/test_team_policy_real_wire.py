import json

from fortress_agent.application.basic_policy import build_basic_policy_runtime
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.memory.world import WorldMemory
from fortress_agent.protocol.codec import GameProtocolCodec


class Deadline:
    def remaining(self):
        return 10
    def expired(self):
        return False


def test_team_planner_outputs_multiple_role_commands_for_day_exploration():
    parsed = GameProtocolCodec().parse_state({
        "roundNo": 10,
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
                    "pos": {"x": 5, "y": 23},
                    "roleType": "worker",
                    "health": 220,
                    "attackPower": 0,
                    "attackRange": 0,
                    "backPackCapability": 100,
                    "backpack": [],
                },
                {
                    "id": 10011,
                    "pos": {"x": 10, "y": 12},
                    "roleType": "pioneer",
                    "health": 200,
                    "attackPower": 0,
                    "attackRange": 0,
                    "backPackCapability": 40,
                    "backpack": [],
                },
                {
                    "id": 10012,
                    "pos": {"x": 10, "y": 16},
                    "roleType": "worker",
                    "health": 220,
                    "attackPower": 0,
                    "attackRange": 0,
                    "backPackCapability": 100,
                    "backpack": [],
                },
            ],
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": []},
        "errors": [],
    })
    assert parsed.ok
    state = parsed.value

    runtime = build_basic_policy_runtime()
    team = runtime.decide_team(
        state=state,
        world_memory=WorldMemory().view(),
        policy_state=PolicyState.create(),
        deadline=Deadline(),
    )

    assert len(team.decisions) == 3

    encoded = runtime.encoder.encode_team(
        team,
        state=state,
        world_memory=WorldMemory().view(),
    )
    assert encoded.ok

    payload = json.loads(encoded.value)
    assert set(payload["roleCommandMap"]) == {
        "10010",
        "10011",
        "10012",
    }
