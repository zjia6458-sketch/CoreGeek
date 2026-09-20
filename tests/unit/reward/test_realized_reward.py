from fortress_agent.reward.realized import (
    MemoryRewardDelta,
    RealizedRewardCalculator,
)
from fortress_agent.protocol.codec import GameProtocolCodec


def parse(payload):
    result = GameProtocolCodec().parse_state(payload)
    assert result.ok, result
    return result.value


def test_realized_reward_uses_score_inventory_information_and_base_hp():
    previous = parse({
        "round": 1,
        "day": 1,
        "phase": "day",
        "my_score": 10,
        "prices": {"iron": 2.0},
        "characters": [{
            "id": 1,
            "role": "worker",
            "hp": 220,
            "position": {"x": 1, "y": 1},
            "inventory": {"iron": 2},
        }],
        "buildings": [{
            "id": "base",
            "type": "base",
            "position": {"x": 0, "y": 0},
            "hp": 100,
            "owner": "self",
        }],
    })

    current = parse({
        "round": 2,
        "day": 1,
        "phase": "day",
        "my_score": 12,
        "prices": {"iron": 2.0},
        "characters": [{
            "id": 1,
            "role": "worker",
            "hp": 220,
            "position": {"x": 1, "y": 1},
            "inventory": {"iron": 5},
        }],
        "buildings": [{
            "id": "base",
            "type": "base",
            "position": {"x": 0, "y": 0},
            "hp": 98,
            "owner": "self",
        }],
    })

    reward = RealizedRewardCalculator().calculate(
        previous,
        current,
        memory_delta=MemoryRewardDelta(
            newly_discovered_cells=2,
            newly_discovered_resources=1,
        ),
    )

    assert reward.score == 2
    assert reward.economy == 6
    assert reward.information == 4
    assert reward.survival == -2
    assert reward.total == 10
