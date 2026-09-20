from dataclasses import dataclass

from fortress_agent.domain.action import MoveAction
from fortress_agent.memory.feedback import RuntimeFeedbackMemory
from fortress_agent.memory.world import WorldMemory
from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.protocol.final_validator import FinalResponseValidator
from fortress_agent.protocol.server_factory import ServerCommandFactory
from fortress_agent.protocol.server_outbound import ServerCommandResponse


@dataclass(frozen=True)
class Exp:
    action: MoveAction


def state(*, zone=True):
    parsed = GameProtocolCodec().parse_state({
        "roundNo": 16,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": ([{
                "neutralType": "defenderTaskPoint1",
                "pos": {"x": 23, "y": 14},
            }] if zone else []),
        },
        "teamOur": {
            "type": "defender",
            "teamId": "4737",
            "teamName": "B",
            "goldNum": 0,
            "totalScore": 0,
            "playerTasks": [],
            "roles": [{
                "id": 20011,
                "pos": {"x": 23, "y": 13},
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


def test_final_validator_rejects_move_onto_taskpoint_before_first_failure():
    response = ServerCommandResponse(
        roleCommandMap={
            "20011": ServerCommandFactory.move((23, 14)),
        }
    )
    result = FinalResponseValidator().validate(
        state=state(zone=True),
        response=response,
    )
    assert "20011" not in result.valid_commands
    assert result.rejected_roles == ("20011",)


def test_final_validator_uses_learned_command_error_even_if_cell_not_in_current_zones():
    feedback = RuntimeFeedbackMemory()
    parsed = GameProtocolCodec().parse_state({
        "roundNo": 17,
        "mapInfo": {"width": 41, "height": 32, "zones": []},
        "teamOur": {
            "type": "defender", "teamId": "4737", "teamName": "B",
            "goldNum": 0, "totalScore": 0, "playerTasks": [],
            "roles": [{
                "id": 20011, "pos": {"x": 23, "y": 13},
                "roleType": "pioneer", "health": 200,
                "attackPower": 0, "attackRange": 0,
                "backPackCapability": 40, "backpack": [],
            }],
        },
        "teamEnemy": {"roles": []}, "robot": {"roles": []},
        "lastRoundRoleActionResults": {"20011": False},
        "errors": [{
            "errorCode": 4,
            "description": "[COMMAND_ERROR] role 20011 wants MOVE to (23,14), but target is impassable terrain [mysteryWall]",
        }],
    })
    assert parsed.ok
    feedback.observe(
        parsed.value,
        previous_experiences=(
            Exp(MoveAction(actor_id=20011, action_type="move", x=23, y=14)),
        ),
    )

    response = ServerCommandResponse(
        roleCommandMap={"20011": ServerCommandFactory.move((23, 14))}
    )
    result = FinalResponseValidator().validate(
        state=state(zone=False),
        response=response,
        world_memory=WorldMemory().view(),
        feedback_memory=feedback.view(),
    )
    assert "20011" not in result.valid_commands


def test_final_validator_applies_failed_move_target_guard_to_other_roles():
    feedback = RuntimeFeedbackMemory(generic_retry_ban_rounds=3)

    feedback_state = GameProtocolCodec().parse_state({
        "roundNo": 16,
        "mapInfo": {"width": 41, "height": 32, "zones": []},
        "teamOur": {
            "type": "defender",
            "teamId": "4737",
            "teamName": "B",
            "goldNum": 0,
            "totalScore": 0,
            "playerTasks": [],
            "roles": [
                {
                    "id": 20011,
                    "pos": {"x": 5, "y": 5},
                    "roleType": "pioneer",
                    "health": 200,
                    "attackPower": 0,
                    "attackRange": 0,
                    "backPackCapability": 40,
                    "backpack": [],
                },
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
            ],
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": []},
        "lastRoundRoleActionResults": {"20011": False},
        "errors": [],
    })
    assert feedback_state.ok

    feedback.observe(
        feedback_state.value,
        previous_experiences=(
            Exp(MoveAction(actor_id=20011, action_type="move", x=5, y=4)),
        ),
    )

    current = GameProtocolCodec().parse_state({
        "roundNo": 17,
        "mapInfo": {"width": 41, "height": 32, "zones": []},
        "teamOur": {
            "type": "defender",
            "teamId": "4737",
            "teamName": "B",
            "goldNum": 0,
            "totalScore": 0,
            "playerTasks": [],
            "roles": [{
                "id": 20010,
                "pos": {"x": 4, "y": 4},
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
    assert current.ok

    # Role 20010 did not cause the original failure, but the coordinate is
    # temporarily protected team-wide.
    response = ServerCommandResponse(
        roleCommandMap={"20010": ServerCommandFactory.move((5, 4))}
    )
    result = FinalResponseValidator().validate(
        state=current.value,
        response=response,
        world_memory=WorldMemory().view(),
        feedback_memory=feedback.view(),
    )

    assert "20010" not in result.valid_commands
    assert result.rejected_roles == ("20010",)
