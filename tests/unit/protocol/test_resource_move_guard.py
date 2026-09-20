from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.protocol.final_validator import FinalResponseValidator
from fortress_agent.protocol.server_factory import ServerCommandFactory
from fortress_agent.protocol.server_outbound import ServerCommandResponse


def state(worker=(4, 23), stone=(4, 24)):
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
    assert result.ok
    return result.value


def test_final_validator_hard_rejects_move_onto_stone_cell():
    response = ServerCommandResponse(
        roleCommandMap={
            "10010": ServerCommandFactory.move((4, 24)),
        }
    )

    result = FinalResponseValidator().validate(
        state=state(),
        response=response,
    )

    assert "10010" not in result.valid_commands
    assert result.rejected_roles == ("10010",)


def test_final_validator_accepts_collect_from_adjacent_cell():
    response = ServerCommandResponse(
        roleCommandMap={
            "10010": ServerCommandFactory.collect((4, 24)),
        }
    )

    result = FinalResponseValidator().validate(
        state=state(),
        response=response,
    )

    assert "10010" in result.valid_commands


def test_final_validator_rejects_collect_from_non_adjacent_cell():
    response = ServerCommandResponse(
        roleCommandMap={
            "10010": ServerCommandFactory.collect((4, 24)),
        }
    )

    result = FinalResponseValidator().validate(
        state=state(worker=(6, 23)),
        response=response,
    )

    assert "10010" not in result.valid_commands
