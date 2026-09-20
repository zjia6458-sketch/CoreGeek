import asyncio
import json

from fortress_agent.application.basic_policy import (
    build_basic_policy_runtime,
)
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.memory.world import WorldMemory
from fortress_agent.protocol.codec import GameProtocolCodec


class Deadline:
    def __init__(self, remaining=10.0):
        self.value = remaining

    def remaining(self):
        return self.value

    def expired(self):
        return self.value <= 0


def parse(payload):
    result = GameProtocolCodec().parse_state(payload)
    assert result.ok, result
    return result.value


def test_full_pipeline_prefers_gather_and_returns_valid_json():
    state = parse({
        "round": 1,
        "day": 1,
        "phase": "day",
        "turns_until_night": 30,
        "prices": {"iron": 2.0},
        "characters": [{
            "id": 1,
            "role": "worker",
            "hp": 220,
            "position": {"x": 5, "y": 5},
            "backpack_capacity": 100,
        }],
    })

    memory = WorldMemory()
    memory.resources.discover(
        resource_id="iron-1",
        resource_type="iron",
        x=5,
        y=6,
        amount=100,
        round_id=1,
    )

    runtime = build_basic_policy_runtime()

    result = asyncio.run(
        runtime.decide_json(
            state=state,
            world_memory=memory.view(),
            policy_state=PolicyState(),
            deadline=Deadline(),
        )
    )

    assert result.ok

    payload = json.loads(result.value)

    assert next(iter(payload["roleCommandMap"].values()))["action"] == "collect"
    assert next(iter(payload["roleCommandMap"].values()))["targetPos"]


def test_full_pipeline_explores_without_resource():
    state = parse({
        "round": 1,
        "day": 1,
        "phase": "day",
        "turns_until_night": 30,
        "characters": [{
            "id": 1,
            "role": "pioneer",
            "hp": 200,
            "position": {"x": 5, "y": 5},
        }],
    })

    runtime = build_basic_policy_runtime()

    result = asyncio.run(
        runtime.decide_json(
            state=state,
            world_memory=WorldMemory().view(),
            policy_state=PolicyState(),
            deadline=Deadline(),
        )
    )

    assert result.ok
    payload = json.loads(result.value)
    assert next(iter(payload["roleCommandMap"].values()))["action"] == "move"


def test_low_deadline_routes_directly_to_emergency():
    state = parse({
        "round": 1,
        "day": 1,
        "phase": "day",
        "characters": [{
            "id": 1,
            "role": "pioneer",
            "hp": 200,
            "position": {"x": 5, "y": 5},
        }],
    })

    runtime = build_basic_policy_runtime()

    decision = asyncio.run(
        runtime.decide(
            state=state,
            world_memory=WorldMemory().view(),
            policy_state=PolicyState(),
            deadline=Deadline(0.2),
        )
    )

    assert decision.strategy_id == "emergency"
    assert decision.action.action_type == "move"
