from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.protocol.final_validator import FinalResponseValidator
from fortress_agent.protocol.server_factory import ServerCommandFactory
from fortress_agent.protocol.server_outbound import ServerCommandResponse


def game_state(*, round_no=85, rocket_cooldown=0):
    result = GameProtocolCodec().parse_state({
        "roundNo": round_no,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": [
                {"neutralType": "stone", "pos": {"x": 4, "y": 24}},
            ],
        },
        "teamOur": {
            "type": "challenger",
            "teamId": "x",
            "teamName": "x",
            "goldNum": 20,
            "totalScore": 0,
            "playerTasks": [],
            "roles": [
                {
                    "id": 10010,
                    "pos": {"x": 4, "y": 23},
                    "roleType": "worker",
                    "health": 220,
                    "attackPower": 0,
                    "attackRange": 0,
                    "backPackCapability": 100,
                    "backpack": ["stone"],
                },
                {
                    "id": 10012,
                    "pos": {"x": 8, "y": 24},
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
                    "backpack": ["Medicine"],
                },
                {
                    "id": 10040,
                    "pos": {"x": 9, "y": 25},
                    "roleType": "rocket",
                    "health": 1000,
                    "attackPower": 20,
                    "attackRange": 100,
                    "level": 1,
                    "cooldown": rocket_cooldown,
                    "backPackCapability": 0,
                    "backpack": [],
                },
            ],
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": []},
        "phaseTask": "",
        "vendorShopList": [
            {"name": "stone", "price": 1},
        ],
        "weaponShopList": [
            {"name": "Medicine", "price": 10},
        ],
        "errors": [],
    })
    assert result.ok, result
    return result.value


def test_attack_is_allowed_at_night_with_weapon_and_controller():
    state = game_state(round_no=85)

    response = ServerCommandResponse(
        roleCommandMap={
            "10040": ServerCommandFactory.attack(
                controller_id="10012",
                points=((5, 20),),
            )
        }
    )

    result = FinalResponseValidator().validate(
        state=state,
        response=response,
    )

    assert "10040" in result.valid_commands


def test_attack_is_rejected_during_day():
    state = game_state(round_no=10)

    response = ServerCommandResponse(
        roleCommandMap={
            "10040": ServerCommandFactory.attack(
                controller_id="10012",
                points=((5, 20),),
            )
        }
    )

    result = FinalResponseValidator().validate(
        state=state,
        response=response,
    )

    assert "10040" not in result.valid_commands


def test_collect_requires_worker_and_current_resource():
    state = game_state(round_no=10)

    response = ServerCommandResponse(
        roleCommandMap={
            "10010": ServerCommandFactory.collect(
                (4, 24)
            )
        }
    )

    result = FinalResponseValidator().validate(
        state=state,
        response=response,
    )

    assert "10010" in result.valid_commands


def test_controller_cannot_also_receive_direct_command():
    state = game_state(round_no=85)

    response = ServerCommandResponse(
        roleCommandMap={
            "10040": ServerCommandFactory.attack(
                controller_id="10012",
                points=((5, 20),),
            ),
            "10010": ServerCommandFactory.move(
                (4, 23)
            ),
        }
    )

    result = FinalResponseValidator().validate(
        state=state,
        response=response,
    )

    assert "10040" in result.valid_commands
    assert "10012" not in result.valid_commands


def test_execute_cmd_is_suppressed_outside_task_by_encoder():
    from fortress_agent.protocol.action_mapper import DecisionResponseEncoder
    from fortress_agent.domain.action import MoveAction
    from fortress_agent.domain.decision import Decision
    from fortress_agent.domain.team import TeamDecision
    from fortress_agent.domain.utility import UtilityBreakdown
    import json

    state = game_state(round_no=10)
    team = TeamDecision(
        decisions=(
            Decision(
                action=MoveAction(
                    actor_id=10010,
                    action_type="move",
                    x=4,
                    y=23,
                ),
                strategy_id="test",
                utility=UtilityBreakdown(total=1),
            ),
        ),
        execute_cmd="python solution.py",
    )

    encoded = DecisionResponseEncoder().encode_team(
        team,
        state=state,
    )

    assert encoded.ok
    assert json.loads(encoded.value)["executeCmd"] == ""
