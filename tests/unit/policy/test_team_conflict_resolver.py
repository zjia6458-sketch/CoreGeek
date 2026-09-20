from fortress_agent.domain.action import AttackAction, MoveAction
from fortress_agent.domain.decision import Decision
from fortress_agent.domain.state import Position
from fortress_agent.domain.utility import UtilityBreakdown
from fortress_agent.policy.team import TeamConflictResolver


def d(action, value):
    return Decision(
        action=action,
        strategy_id="defense",
        utility=UtilityBreakdown(total=value),
    )


def test_same_controller_can_only_control_one_weapon():
    decisions = (
        d(
            AttackAction(
                actor_id=10020,
                action_type="attack",
                controller_id=10010,
                targets=(Position(1, 1),),
            ),
            10,
        ),
        d(
            AttackAction(
                actor_id=10040,
                action_type="attack",
                controller_id=10010,
                targets=(Position(2, 2),),
            ),
            5,
        ),
    )

    result = TeamConflictResolver().resolve(decisions)

    assert len(result.team_decision.decisions) == 1
    assert result.team_decision.decisions[0].action.actor_id == 10020


def test_controller_own_action_conflicts_with_weapon_control():
    decisions = (
        d(
            AttackAction(
                actor_id=10020,
                action_type="attack",
                controller_id=10010,
                targets=(Position(1, 1),),
            ),
            10,
        ),
        d(
            MoveAction(
                actor_id=10010,
                action_type="move",
                x=2,
                y=2,
            ),
            3,
        ),
    )

    result = TeamConflictResolver().resolve(decisions)

    assert len(result.team_decision.decisions) == 1
    assert result.team_decision.decisions[0].action.actor_id == 10020
