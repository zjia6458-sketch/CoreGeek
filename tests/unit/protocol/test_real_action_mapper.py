import json

from fortress_agent.domain.action import GatherAction, MoveAction
from fortress_agent.domain.decision import Decision
from fortress_agent.domain.utility import UtilityBreakdown
from fortress_agent.memory.world import WorldMemory
from fortress_agent.protocol.action_mapper import DecisionResponseEncoder


def decision(action):
    return Decision(
        action=action,
        strategy_id="test",
        utility=UtilityBreakdown(total=1.0),
    )


def test_move_decision_encodes_to_role_command_map():
    result = DecisionResponseEncoder().encode(
        decision(
            MoveAction(
                actor_id=10010,
                action_type="move",
                x=29,
                y=7,
            )
        )
    )

    assert result.ok
    payload = json.loads(result.value)

    assert payload["roleCommandMap"]["10010"] == {
        "action": "move",
        "targetPos": [{"x": 29, "y": 7}],
    }


def test_gather_maps_to_collect_using_resource_memory_position():
    memory = WorldMemory()
    memory.resources.discover(
        resource_id="zone:stone:4:24",
        resource_type="stone",
        x=4,
        y=24,
        amount=None,
        round_id=1,
    )

    result = DecisionResponseEncoder().encode(
        decision(
            GatherAction(
                actor_id=10010,
                action_type="gather",
                resource_id="zone:stone:4:24",
            )
        ),
        world_memory=memory.view(),
    )

    assert result.ok
    payload = json.loads(result.value)

    assert payload["roleCommandMap"]["10010"] == {
        "action": "collect",
        "targetPos": [{"x": 4, "y": 24}],
    }


def test_gather_without_memory_fails_locally_instead_of_emitting_bad_json():
    result = DecisionResponseEncoder().encode(
        decision(
            GatherAction(
                actor_id=10010,
                action_type="gather",
                resource_id="zone:stone:4:24",
            )
        )
    )

    assert not result.ok
    assert result.error_code == "domain_action_mapping_error"
