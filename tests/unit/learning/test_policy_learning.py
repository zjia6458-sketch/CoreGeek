from fortress_agent.domain.action import GatherAction
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.domain.reward import RewardBreakdown
from fortress_agent.domain.utility import UtilityBreakdown
from fortress_agent.learning.experience.record import (
    ExperienceRecord,
    OutcomeRecord,
)
from fortress_agent.learning.learners.utility import UtilityWeightLearner
from fortress_agent.learning.policy_repository import InMemoryPolicyStateRepository


def experience(i):
    return ExperienceRecord(
        experience_id=f"e{i}",
        decision_id=f"d{i}",
        round_id=i,
        day=1,
        phase="day",
        policy_version=1,
        strategy_id="gather",
        feature_schema_version=1,
        feature_vector=(),
        action=GatherAction(
            actor_id=1,
            action_type="gather",
            resource_id="iron",
        ),
        action_probability=1.0,
        predicted_utility=UtilityBreakdown(total=2.0),
        latency_ms=1.0,
        deadline_remaining_ms=1000.0,
    )


def outcome(i):
    return OutcomeRecord(
        outcome_id=f"o{i}",
        start_round=i,
        end_round=i + 1,
        reward=RewardBreakdown(total=5.0),
    )


def test_learner_proposes_patch_without_mutating_current_policy():
    current = PolicyState.create(
        version=1,
        utility_weights={"economy": 1.0},
    )

    learner = UtilityWeightLearner(
        min_samples=5,
        learning_rate=0.1,
    )

    for i in range(5):
        learner.observe(
            experience(i),
            outcome(i),
        )

    patch = learner.propose(current)

    assert patch is not None
    assert current.utility_weights["economy"] == 1.0
    assert patch.new_value == 1.1


def test_policy_repository_creates_candidate_then_promotes():
    initial = PolicyState.create(
        version=1,
        utility_weights={"economy": 1.0},
    )
    repo = InMemoryPolicyStateRepository(initial)

    learner = UtilityWeightLearner(
        min_samples=1,
        learning_rate=0.1,
    )
    learner.observe(
        experience(1),
        outcome(1),
    )
    patch = learner.propose(initial)
    assert patch is not None

    candidate = repo.create_candidate(patch)

    assert candidate.version == 2
    assert candidate.utility_weights["economy"] == 1.1
    assert repo.current().version == 1

    repo.promote(candidate.version)

    assert repo.current().version == 2

    repo.rollback(1)

    assert repo.current().version == 1
