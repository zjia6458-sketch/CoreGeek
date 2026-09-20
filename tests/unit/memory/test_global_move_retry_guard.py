from dataclasses import dataclass

from fortress_agent.domain.action import MoveAction
from fortress_agent.memory.feedback import RuntimeFeedbackMemory
from fortress_agent.protocol.codec import GameProtocolCodec


@dataclass(frozen=True)
class Exp:
    action: MoveAction


def state(round_no: int, role_results):
    parsed = GameProtocolCodec().parse_state({
        "roundNo": round_no,
        "mapInfo": {"width": 41, "height": 32, "zones": []},
        "teamOur": {
            "type": "defender",
            "teamId": "x",
            "teamName": "x",
            "goldNum": 0,
            "totalScore": 0,
            "playerTasks": [],
            "roles": [
                {
                    "id": 20010,
                    "pos": {"x": 4, "y": 4},
                    "roleType": "worker",
                    "health": 220,
                    "attackPower": 0,
                    "attackRange": 0,
                    "backPackCapability": 100,
                    "backpack": [],
                },
                {
                    "id": 20011,
                    "pos": {"x": 6, "y": 4},
                    "roleType": "pioneer",
                    "health": 200,
                    "attackPower": 0,
                    "attackRange": 0,
                    "backPackCapability": 40,
                    "backpack": [],
                },
                {
                    "id": 20012,
                    "pos": {"x": 5, "y": 3},
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
        "lastRoundRoleActionResults": role_results,
        "errors": [],
    })
    assert parsed.ok
    return parsed.value


def test_one_failed_move_temporarily_blocks_same_target_for_all_roles():
    memory = RuntimeFeedbackMemory(generic_retry_ban_rounds=3)
    failed = MoveAction(
        actor_id=20011,
        action_type="move",
        x=5,
        y=4,
    )

    record = memory.observe(
        state(16, {"20011": False}),
        previous_experiences=(Exp(failed),),
    )

    failure = record.action_failures[0]
    assert failure.retry_scope == "all_roles_same_move_target"
    assert failure.move_target_x == 5
    assert failure.move_target_y == 4

    view = memory.view()
    for role_id in (20010, 20011, 20012):
        assert view.is_move_retry_blocked(role_id, 5, 4, 16)
        assert view.is_move_retry_blocked(role_id, 5, 4, 19)

    # Different coordinate remains available: the temporary rule is precise.
    assert not view.is_move_retry_blocked(20010, 5, 5, 16)


def test_team_wide_move_ban_expires_without_semantic_terrain_evidence():
    memory = RuntimeFeedbackMemory(generic_retry_ban_rounds=2)
    failed = MoveAction(
        actor_id=20011,
        action_type="move",
        x=5,
        y=4,
    )
    memory.observe(
        state(10, {"20011": False}),
        previous_experiences=(Exp(failed),),
    )

    view = memory.view()
    assert view.is_move_retry_blocked(20010, 5, 4, 12)
    assert not view.is_move_retry_blocked(20010, 5, 4, 13)
    assert view.terrain_rules() == ()
