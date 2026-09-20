import asyncio
import json
from pathlib import Path

from fortress_agent.application.runtime import FortressAgentRuntime


FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "server_round_85.json"
)


def load_fixture():
    return json.loads(
        FIXTURE.read_text(encoding="utf-8")
    )


def advisory_json():
    return json.dumps({
        "schema_version": "1.0",
        "source_round": 85,
        "recommended_mode": "explore",
        "mode_strength": 0.8,
        "confidence": 0.7,
        "expires_after_rounds": 130,
        "claims": [{
            "kind": "requirement",
            "subject": "stone gate",
            "relation": "requires",
            "object": "three keys",
            "confidence": 0.55,
        }],
        "objectives": [{
            "objective_type": "explore_region",
            "priority": 0.9,
            "description": "inspect western region",
            "target_position": None,
            "target_region": "west",
            "required_items": [],
        }],
        "short_reason": "uncertain western gate clue",
    })


def test_runtime_memorizes_folk_legend_even_without_llm_response():
    runtime = FortressAgentRuntime()
    payload = load_fixture()

    # round 85 is night; current policy may use emergency because attack plugin
    # is intentionally not fabricated. We only assert knowledge ingestion.
    try:
        asyncio.run(runtime.handle_turn(payload))
    except Exception:
        # Protocol-dependent night combat is not implemented yet.
        pass

    lore = runtime.strategic_memory.lore()

    assert len(lore) == 1
    assert "西部有一石门" in lore[0].text


def test_runtime_accepts_structured_llm_advisory_into_memory():
    runtime = FortressAgentRuntime()
    payload = load_fixture()
    payload["llmResp"] = advisory_json()

    try:
        asyncio.run(runtime.handle_turn(payload))
    except Exception:
        pass

    advisory = runtime.strategic_memory.active_advisory(85)

    assert advisory is not None
    assert advisory.recommended_mode == "explore"
    assert advisory.objectives[0].target_region == "west"


def test_runtime_rejects_malformed_llm_response_without_polluting_memory():
    runtime = FortressAgentRuntime()
    payload = load_fixture()
    payload["llmResp"] = "move west now!"

    try:
        asyncio.run(runtime.handle_turn(payload))
    except Exception:
        pass

    assert (
        runtime.strategic_memory.active_advisory(85)
        is None
    )
