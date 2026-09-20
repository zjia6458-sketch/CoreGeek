from types import MappingProxyType

from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.llm.parser import StrategicLLMResponseParser
from fortress_agent.memory.strategic import StrategicMemory
from fortress_agent.memory.world import WorldMemory
from fortress_agent.policy.context import PolicyContext
from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.strategies.basic import BasicStrategySelector


class Deadline:
    def remaining(self):
        return 10
    def expired(self):
        return False


def make_ctx(*, phase="day", remaining=30, advisory=True):
    parsed = GameProtocolCodec().parse_state({
        "round": 85,
        "day": 1,
        "phase": phase,
        "turns_until_night": remaining,
        "characters": [{
            "id": 1,
            "role": "pioneer",
            "hp": 200,
            "position": {"x": 10, "y": 12},
        }],
    })
    assert parsed.ok

    strategic = StrategicMemory()

    if advisory:
        result = StrategicLLMResponseParser().parse({
            "schema_version": "1.0",
            "source_round": 85,
            "recommended_mode": "explore",
            "mode_strength": 0.8,
            "confidence": 0.7,
            "expires_after_rounds": 130,
            "claims": [],
            "objectives": [],
            "short_reason": "",
        })
        assert result.ok
        strategic.add_advisory(result.value)

    return PolicyContext(
        state=parsed.value,
        world_memory=WorldMemory().view(),
        policy_state=PolicyState.create(),
        deadline=Deadline(),
        features=MappingProxyType({}),
        strategic_memory=strategic.view(),
    )


def test_valid_strong_llm_advisory_can_bias_long_term_mode():
    strategy = BasicStrategySelector().select(
        make_ctx()
    )

    assert strategy.strategy_id == "llm_explore"


def test_llm_advisory_cannot_override_night_defense():
    strategy = BasicStrategySelector().select(
        make_ctx(phase="night")
    )

    assert strategy.strategy_id == "defense"


def test_llm_advisory_cannot_override_prepare_deadline():
    strategy = BasicStrategySelector().select(
        make_ctx(remaining=3)
    )

    assert strategy.strategy_id == "prepare"
