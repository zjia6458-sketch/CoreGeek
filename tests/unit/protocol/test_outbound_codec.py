import json
import pytest
from pydantic import ValidationError

from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.protocol.factory import CommandFactory
from fortress_agent.protocol.outbound import AttackCommand, GameActionResponse


def test_move_response_serializes_to_strict_json():
    response = GameActionResponse(
        actions=(CommandFactory.move(actor_id=1, x=4, y=5),)
    )
    result = GameProtocolCodec().serialize_response(response)

    assert result.ok
    assert json.loads(result.value) == {
        "actions": [{
            "command": "move",
            "actor_id": 1,
            "target": {"x": 4, "y": 5},
        }]
    }


def test_attack_requires_target():
    with pytest.raises(ValidationError):
        AttackCommand(actor_id=1)


def test_output_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        GameActionResponse.model_validate({
            "actions": [{
                "command": "move",
                "actor_id": 1,
                "target": {"x": 1, "y": 2},
                "unexpected": "bad",
            }]
        })


def test_output_coordinate_must_be_inside_map():
    with pytest.raises(ValidationError):
        CommandFactory.move(actor_id=1, x=41, y=0)
