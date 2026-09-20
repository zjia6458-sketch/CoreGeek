from types import MappingProxyType

from fortress_agent.domain.action import MoveAction
from fortress_agent.domain.decision import Decision
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.domain.utility import UtilityBreakdown
from fortress_agent.evolution.estimators.base import (
    CounterfactualEstimatorRegistry,
)
from fortress_agent.evolution.estimators.direct import DirectUtilityEstimator
from fortress_agent.evolution.estimators.exact import ExactSameActionEstimator
from fortress_agent.learning.experience.store import InMemoryExperienceStore
from fortress_agent.memory.world import WorldMemory
from fortress_agent.policy.context import PolicyContext
from fortress_agent.protocol.codec import GameProtocolCodec


class Deadline:
    def remaining(self):
        return 1
    def expired(self):
        return False


def ctx():
    parsed = GameProtocolCodec().parse_state({
        "round": 1,
        "day": 1,
        "phase": "day",
    })
    assert parsed.ok

    return PolicyContext(
        state=parsed.value,
        world_memory=WorldMemory().view(),
        policy_state=PolicyState.create(),
        deadline=Deadline(),
        features=MappingProxyType({}),
    )


def decision(action, utility):
    return Decision(
        action=action,
        strategy_id="explore",
        utility=UtilityBreakdown(
            total=utility,
            risk=0.1,
        ),
    )


def test_exact_estimator_has_priority_for_same_action():
    action = MoveAction(
        actor_id=1,
        action_type="move",
        x=1,
        y=2,
    )
    current = decision(action, 1.0)
    candidate = decision(action, 2.0)

    registry = CounterfactualEstimatorRegistry()
    registry.register(DirectUtilityEstimator())
    registry.register(ExactSameActionEstimator())

    estimator = registry.resolve(
        ctx(),
        current,
        candidate,
    )

    assert estimator.estimator_id == "exact_same_action"


def test_direct_estimator_falls_back_for_different_actions():
    current = decision(
        MoveAction(
            actor_id=1,
            action_type="move",
            x=1,
            y=2,
        ),
        1.0,
    )
    candidate = decision(
        MoveAction(
            actor_id=1,
            action_type="move",
            x=2,
            y=1,
        ),
        2.0,
    )

    registry = CounterfactualEstimatorRegistry()
    registry.register(ExactSameActionEstimator())
    registry.register(DirectUtilityEstimator())

    estimator = registry.resolve(
        ctx(),
        current,
        candidate,
    )

    assert estimator.estimator_id == "direct_utility"
