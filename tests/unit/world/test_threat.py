from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.world.threat import ThreatMapBuilder


def parse(payload):
    result = GameProtocolCodec().parse_state(payload)
    assert result.ok, result
    return result.value


def test_enemy_closer_to_base_produces_higher_base_risk():
    builder = ThreatMapBuilder()

    far = parse({
        "round": 1,
        "day": 1,
        "phase": "night",
        "buildings": [{
            "id": "base",
            "type": "base",
            "position": {"x": 0, "y": 0},
            "hp": 100,
            "owner": "self",
        }],
        "robots": [{
            "id": "e",
            "type": "large",
            "hp": 500,
            "attack": 20,
            "position": {"x": 20, "y": 20},
        }],
    })

    near = parse({
        "round": 1,
        "day": 1,
        "phase": "night",
        "buildings": [{
            "id": "base",
            "type": "base",
            "position": {"x": 0, "y": 0},
            "hp": 100,
            "owner": "self",
        }],
        "robots": [{
            "id": "e",
            "type": "large",
            "hp": 500,
            "attack": 20,
            "position": {"x": 2, "y": 1},
        }],
    })

    _, far_snapshot = builder.build(far)
    _, near_snapshot = builder.build(near)

    assert near_snapshot.base_risk > far_snapshot.base_risk
    assert near_snapshot.nearest_enemy_eta == 3


def test_threat_is_highest_near_enemy_source():
    state = parse({
        "round": 1,
        "day": 1,
        "phase": "night",
        "robots": [{
            "id": "e",
            "type": "small",
            "hp": 40,
            "attack": 5,
            "position": {"x": 5, "y": 5},
        }],
    })

    threat, _ = ThreatMapBuilder().build(state)

    assert threat.value(5, 5) > threat.value(8, 5)
