from fortress_agent.llm.parser import (
    StrategicLLMResponseParser,
)


VALID = {
    "schema_version": "1.0",
    "source_round": 85,
    "recommended_mode": "explore",
    "mode_strength": 0.8,
    "confidence": 0.6,
    "expires_after_rounds": 130,
    "claims": [
        {
            "kind": "location_hint",
            "subject": "stone gate",
            "relation": "located_in",
            "object": "west",
            "confidence": 0.55,
        },
        {
            "kind": "requirement",
            "subject": "stone gate",
            "relation": "requires",
            "object": "three keys",
            "confidence": 0.55,
        },
    ],
    "objectives": [
        {
            "objective_type": "explore_region",
            "priority": 0.8,
            "description": "collect evidence in the western region",
            "target_position": None,
            "target_region": "west",
            "required_items": [],
        }
    ],
    "short_reason": "Legend suggests a western gated location but evidence is uncertain.",
}


def test_valid_llm_json_is_parsed_and_strength_is_derived():
    result = StrategicLLMResponseParser().parse(
        VALID
    )

    assert result.ok
    assert result.value.recommended_mode == "explore"
    assert abs(
        result.value.effective_strength - 0.48
    ) < 1e-9


def test_markdown_prose_is_rejected():
    result = StrategicLLMResponseParser().parse(
        "I think you should explore west."
    )

    assert not result.ok
    assert result.error_code == "llm_invalid_json"


def test_unknown_field_is_rejected():
    payload = dict(VALID)
    payload["execute_command"] = "move west"

    result = StrategicLLMResponseParser().parse(
        payload
    )

    assert not result.ok
    assert result.error_code == "llm_schema_validation_error"


def test_single_json_code_fence_is_tolerated():
    import json

    result = StrategicLLMResponseParser().parse(
        "```json\n"
        + json.dumps(VALID)
        + "\n```"
    )

    assert result.ok
