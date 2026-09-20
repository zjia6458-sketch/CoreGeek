from fortress_agent.domain.action import MoveAction
from fortress_agent.domain.reward import RewardBreakdown
from fortress_agent.domain.utility import UtilityBreakdown
from fortress_agent.learning.experience.credit import TeamCreditAssigner
from fortress_agent.learning.experience.record import ExperienceRecord


def exp(role_id):
    return ExperienceRecord(
        experience_id=f"e{role_id}",
        decision_id=f"d{role_id}",
        round_id=1,
        day=1,
        phase="day",
        policy_version=1,
        strategy_id="explore",
        feature_schema_version=1,
        feature_vector=(),
        action=MoveAction(
            actor_id=role_id,
            action_type="move",
            x=1,
            y=1,
        ),
        action_probability=1.0,
        predicted_utility=UtilityBreakdown(total=1.0),
        latency_ms=0.0,
        deadline_remaining_ms=1000.0,
    )


def test_team_reward_is_split_across_non_illegal_actions():
    rows = TeamCreditAssigner().assign(
        experiences=(exp(1), exp(2), exp(3)),
        reward=RewardBreakdown(total=9.0, score=9.0),
        legality={
            "1": True,
            "2": False,
            "3": True,
        },
    )

    values = {
        str(e.action.actor_id): (r.total, legal)
        for e, r, legal in rows
    }

    assert values["1"] == (4.5, True)
    assert values["2"] == (0.0, False)
    assert values["3"] == (4.5, True)
