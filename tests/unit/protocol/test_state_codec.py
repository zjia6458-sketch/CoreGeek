from fortress_agent.protocol.codec import GameProtocolCodec

VALID_STATE = {
    "round": 12,
    "day": 1,
    "phase": "DAY",
    "phase_round": 12,
    "turns_until_night": 58,
    "my_score": 10,
    "opponent_score": 9,
    "anomaly_count": 0,
    "characters": [{
        "id": 1,
        "role": "Worker",
        "hp": 220,
        "max_hp": 220,
        "position": {"x": 3, "y": 4},
        "backpack_capacity": 100,
        "inventory": {"iron": 10},
    }],
    "robots": [{
        "id": "r1",
        "type": "small",
        "hp": 40,
        "attack": 5,
        "score": 1,
        "position": {"x": 10, "y": 8},
    }],
    "resources": [{
        "id": "mine-1",
        "type": "iron",
        "position": {"x": 5, "y": 5},
        "amount": 100,
    }],
    "tasks": [],
    "news": ["iron demand rises"],
    "rumors": [],
    "prices": {"iron": 2.5},
}


def test_parse_valid_state_builds_domain_state():
    result = GameProtocolCodec().parse_state(VALID_STATE)
    assert result.ok
    assert result.value.round_id == 12
    assert result.value.phase == "day"
    assert result.value.characters[0].role == "worker"
    assert result.value.enemies[0].enemy_type == "small"


def test_parse_accepts_server_wrapper():
    result = GameProtocolCodec().parse_state({"data": VALID_STATE})
    assert result.ok
    assert result.value.round_id == 12


def test_parse_accepts_unknown_inbound_fields():
    state = dict(VALID_STATE)
    state["future_server_field"] = {"new": "value"}
    assert GameProtocolCodec().parse_state(state).ok


def test_parse_invalid_json_returns_result_not_exception():
    result = GameProtocolCodec().parse_state("{broken-json")
    assert not result.ok
    assert result.error_code == "invalid_json"


def test_missing_round_returns_structured_validation_issue():
    state = dict(VALID_STATE)
    state.pop("round")
    result = GameProtocolCodec().parse_state(state)
    assert not result.ok
    assert result.error_code == "state_validation_error"
    assert any(issue.path == "round_id" for issue in result.issues)


def test_out_of_map_position_is_rejected():
    state = dict(VALID_STATE)
    state["characters"] = [{
        "id": 1,
        "role": "worker",
        "hp": 220,
        "position": {"x": 99, "y": 4},
    }]
    result = GameProtocolCodec().parse_state(state)
    assert not result.ok
    assert result.error_code == "state_validation_error"
