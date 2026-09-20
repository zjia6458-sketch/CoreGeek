from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.features.threat import ThreatFeatureExtractor
from fortress_agent.memory.world import WorldMemory
from fortress_agent.protocol.codec import GameProtocolCodec


def test_threat_feature_exposes_real_base_risk():
    parsed = GameProtocolCodec().parse_state({
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
            "type": "medium",
            "hp": 60,
            "attack": 10,
            "position": {"x": 1, "y": 0},
        }],
    })
    assert parsed.ok

    features = ThreatFeatureExtractor().extract(
        parsed.value,
        WorldMemory().view(),
        PolicyState(),
    )

    assert features["combat.base_risk"] > 0
    assert features["combat.enemy_count"] == 1
    assert features["combat.nearest_enemy_eta"] == 1
