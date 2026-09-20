import asyncio
import json

from fortress_agent.application.runtime import FortressAgentRuntime
from fortress_agent.observability.sinks import InMemoryTraceSink


def test_runtime_accepts_raw_json_and_returns_valid_json():
    runtime = FortressAgentRuntime()

    result = asyncio.run(
        runtime.handle_turn({
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
    )

    assert result.ok
    assert result.game_state.round_id == 1
    assert result.decision is not None

    payload = json.loads(result.response_json)
    assert next(iter(payload["roleCommandMap"].values()))["action"] == "move"


def test_runtime_second_turn_calculates_realized_reward():
    runtime = FortressAgentRuntime()

    first = asyncio.run(
        runtime.handle_turn({
            "round": 1,
            "day": 1,
            "phase": "day",
            "my_score": 0,
            "characters": [{
                "id": 1,
                "role": "pioneer",
                "hp": 200,
                "position": {"x": 5, "y": 5},
            }],
        })
    )
    assert first.ok
    assert first.realized_reward is None

    second = asyncio.run(
        runtime.handle_turn({
            "round": 2,
            "day": 1,
            "phase": "day",
            "my_score": 3,
            "characters": [{
                "id": 1,
                "role": "pioneer",
                "hp": 200,
                "position": {"x": 5, "y": 6},
            }],
        })
    )

    assert second.ok
    assert second.realized_reward is not None
    assert second.realized_reward.score == 3


def test_runtime_emits_turn_trace():
    trace = InMemoryTraceSink()
    runtime = FortressAgentRuntime(
        trace_sink=trace,
    )

    result = asyncio.run(
        runtime.handle_turn({
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
    )

    assert result.ok
    assert any(
        event.kind == "turn_completed"
        for event in trace.events
    )
    assert any(
        event.kind == "policy_node_completed"
        for event in trace.events
    )
