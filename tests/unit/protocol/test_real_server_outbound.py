import json

import pytest
from pydantic import ValidationError

from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.protocol.server_factory import ServerCommandFactory
from fortress_agent.protocol.server_outbound import (
    AttackRoleCommand,
    ServerCommandResponse,
    SummonTreasureRoleCommand,
    UseRoleCommand,
)


def test_real_role_command_map_serializes_exact_wire_names():
    response = ServerCommandResponse(
        roleCommandMap={
            "10010": ServerCommandFactory.move(
                (29, 7)
            ),
            "10020": ServerCommandFactory.attack(
                controller_id=10010,
                points=((29, 7),),
            ),
            "10011": ServerCommandFactory.sell(
                "stone",
                1,
            ),
            "10012": ServerCommandFactory.buy(
                "Medicine",
                1,
            ),
        },
        prompt="",
        executeCmd="",
    )

    result = GameProtocolCodec().serialize_server_response(
        response
    )

    assert result.ok
    payload = json.loads(result.value)

    assert payload == {
        "roleCommandMap": {
            "10010": {
                "action": "move",
                "targetPos": [
                    {"x": 29, "y": 7}
                ],
            },
            "10020": {
                "action": "attack",
                "controllerId": "10010",
                "targetPos": [
                    {"x": 29, "y": 7}
                ],
            },
            "10011": {
                "action": "sell",
                "name": "stone",
                "num": 1,
            },
            "10012": {
                "action": "buy",
                "name": "Medicine",
                "num": 1,
            },
        },
        "prompt": "",
        "executeCmd": "",
    }


def test_all_real_command_shapes_can_be_constructed():
    commands = {
        "move": ServerCommandFactory.move((29, 7)),
        "attack": ServerCommandFactory.attack(
            controller_id="10010",
            points=((29, 7),),
        ),
        "sell": ServerCommandFactory.sell("stone", 1),
        "buy": ServerCommandFactory.buy("Medicine", 1),
        "build": ServerCommandFactory.build(
            "wall",
            (29, 7),
        ),
        "remove": ServerCommandFactory.remove((29, 7)),
        "acceptTask": ServerCommandFactory.accept_task(),
        "submitAnswer": ServerCommandFactory.submit_answer("xxx"),
        "summonTreasure": ServerCommandFactory.summon_treasure(
            points=((29, 7),),
            items=(
                "AcientTablet",
                "StarSand",
                "FlameBreath",
            ),
        ),
        "use_no_target": ServerCommandFactory.use(
            "Medicine"
        ),
        "use_target": ServerCommandFactory.use(
            "WallFixer",
            points=((29, 7),),
        ),
        "drop": ServerCommandFactory.drop("stone"),
        "collect": ServerCommandFactory.collect((29, 7)),
    }

    assert commands["move"].action == "move"
    assert commands["remove"].action == "remove"
    assert commands["acceptTask"].action == "acceptTask"
    assert commands["collect"].action == "collect"


def test_non_empty_attack_controller_is_enforced():
    with pytest.raises(ValidationError):
        AttackRoleCommand(
            controllerId="   ",
            targetPos=[{"x": 1, "y": 1}],
        )


def test_non_empty_target_positions_are_enforced_for_required_commands():
    with pytest.raises(ValidationError):
        ServerCommandFactory.move()


def test_summon_treasure_requires_at_least_one_item():
    with pytest.raises(ValidationError):
        SummonTreasureRoleCommand(
            targetPos=[{"x": 1, "y": 1}],
            item=[],
        )


def test_use_target_position_is_optional_and_empty_is_normalized():
    no_target = UseRoleCommand(
        name="Medicine",
        targetPos=[],
    )

    assert no_target.targetPos is None


def test_prompt_and_execute_cmd_accept_none_as_empty():
    response = ServerCommandResponse(
        roleCommandMap={},
        prompt=None,
        executeCmd=None,
    )

    assert response.prompt == ""
    assert response.executeCmd == ""
