from fortress_agent.protocol.codec import GameProtocolCodec


def test_protocol_builds_explicit_observed_cells():
    result = GameProtocolCodec().parse_state(
        {
            "round": 1,
            "day": 1,
            "phase": "day",
            "visible_cells": [
                {"x": 3, "y": 4, "terrain": "grass"},
                {"x": 4, "y": 4, "terrain": "road"},
            ],
        }
    )

    assert result.ok
    assert len(result.value.observed_cells) == 2
    assert result.value.observed_cells[1].terrain == "road"
