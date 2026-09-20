from types import MappingProxyType

from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.domain.reward import RewardBreakdown
from fortress_agent.memory.world import WorldMemory
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.strategy import StrategyProfile
from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.reward.utility import UtilityComposer


class Deadline:
    def remaining(self):
        return 10.0
    def expired(self):
        return False


def test_strategy_weights_change_utility_not_raw_reward():
    parsed = GameProtocolCodec().parse_state({
        "round": 1,
        "day": 1,
        "phase": "day",
    })
    assert parsed.ok

    ctx = PolicyContext(
        state=parsed.value,
        world_memory=WorldMemory().view(),
        policy_state=PolicyState(),
        deadline=Deadline(),
        features=MappingProxyType({}),
    )

    reward = RewardBreakdown(
        economy=10,
        information=2,
        risk=1,
        action_cost=1,
        total=10,
    )

    normal = StrategyProfile(
        strategy_id="normal",
        candidate_tags=frozenset(),
    )
    economy = StrategyProfile(
        strategy_id="economy",
        candidate_tags=frozenset(),
        utility_weight_overrides=MappingProxyType({
            "economy": 2.0,
        }),
    )

    composer = UtilityComposer()

    u1 = composer.compose(ctx, normal, reward)
    u2 = composer.compose(ctx, economy, reward)

    assert reward.economy == 10
    assert u2.total > u1.total
