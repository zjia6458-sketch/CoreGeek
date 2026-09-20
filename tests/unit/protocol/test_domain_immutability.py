import pytest
from fortress_agent.protocol.codec import GameProtocolCodec


def test_market_prices_are_read_only():
    result = GameProtocolCodec().parse_state({
        "round": 1,
        "day": 1,
        "phase": "day",
        "prices": {"iron": 2.0},
    })
    assert result.ok

    with pytest.raises(TypeError):
        result.value.market_prices["iron"] = 99.0
