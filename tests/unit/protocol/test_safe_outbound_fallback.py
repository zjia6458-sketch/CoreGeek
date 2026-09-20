from fortress_agent.protocol.safe_outbound import (
    SafeServerResponseBuilder,
    StaticRoleCommandFallback,
)
from fortress_agent.protocol.server_factory import ServerCommandFactory


def test_invalid_required_field_omits_role_by_default():
    builder = SafeServerResponseBuilder()

    result = builder.build({
        "10010": {
            "action": "move",
            "targetPos": [],
        }
    })

    assert result.degraded
    assert result.response.roleCommandMap == {}
    assert result.omitted_roles == ("10010",)
    assert result.failures[0].error_code == "invalid_role_command"


def test_known_good_static_fallback_replaces_invalid_command():
    builder = SafeServerResponseBuilder(
        fallback=StaticRoleCommandFallback({
            "10010": ServerCommandFactory.move(
                (5, 24)
            )
        })
    )

    result = builder.build({
        "10010": {
            "action": "move",
            "targetPos": [],
        }
    })

    assert result.fallback_roles == ("10010",)
    assert (
        result.response.roleCommandMap["10010"]
        .targetPos[0].x
        == 5
    )


def test_invalid_fallback_is_also_rejected_and_role_is_omitted():
    builder = SafeServerResponseBuilder(
        fallback=StaticRoleCommandFallback({
            "10010": {
                "action": "sell",
                "name": "",
                "num": 0,
            }
        })
    )

    result = builder.build({
        "10010": {
            "action": "move",
            "targetPos": [],
        }
    })

    assert result.response.roleCommandMap == {}
    assert result.omitted_roles == ("10010",)
    assert any(
        x.error_code == "invalid_fallback_command"
        for x in result.failures
    )


def test_empty_role_map_is_legal_fallback_envelope():
    result = SafeServerResponseBuilder().build(
        {},
        prompt=None,
        execute_cmd=None,
    )

    assert not result.degraded
    assert result.response.roleCommandMap == {}
    assert result.response.prompt == ""
    assert result.response.executeCmd == ""
