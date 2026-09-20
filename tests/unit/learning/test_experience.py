from types import MappingProxyType

from fortress_agent.domain.action import MoveAction
from fortress_agent.domain.decision import Decision
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.domain.reward import RewardBreakdown
from fortress_agent.domain.utility import UtilityBreakdown
from fortress_agent.learning.experience.builder import ExperienceBuilder
from fortress_agent.learning.experience.stats import ContextKey
from fortress_agent.learning.experience.store import InMemoryExperienceStore
from fortress_agent.memory.world import WorldMemory
from fortress_agent.policy.context import PolicyContext
from fortress_agent.protocol.codec import GameProtocolCodec


class Deadline:
    def remaining(self):
        return 2.0
    def expired(self):
        return False


def context():
    parsed = GameProtocolCodec().parse_state({
        "round": 10,
        "day": 1,
        "phase": "day",
    })
    assert parsed.ok

    return PolicyContext(
        state=parsed.value,
        world_memory=WorldMemory().view(),
        policy_state=PolicyState.create(version=3),
        deadline=Deadline(),
        features=MappingProxyType({
            "score.gap": 2.0,
            "time.phase": "day",
        }),
    )


def test_experience_builder_and_store_attach_outcome():
    ctx = context()
    builder = ExperienceBuilder()

    decision = Decision(
        action=MoveAction(
            actor_id=1,
            action_type="move",
            x=1,
            y=2,
        ),
        strategy_id="explore",
        utility=UtilityBreakdown(total=3.0),
        policy_version=3,
    )

    exp = builder.build_decision(
        ctx=ctx,
        decision=decision,
    )

    outcome, credit = builder.build_outcome(
        previous=exp,
        reward=RewardBreakdown(total=5.0),
        end_round=11,
    )

    store = InMemoryExperienceStore()
    store.append(exp)
    store.attach_outcome(
        outcome,
        (credit,),
    )

    assert store.outcome_for(
        exp.decision_id
    ) == outcome

    stats = store.aggregate(
        ContextKey(
            phase="day",
            strategy_id="explore",
            action_type="move",
        )
    )

    assert stats.count == 1
    assert stats.mean == 5.0
