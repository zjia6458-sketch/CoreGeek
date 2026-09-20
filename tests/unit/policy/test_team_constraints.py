from types import MappingProxyType

from fortress_agent.domain.action import BuyAction
from fortress_agent.domain.decision import Decision
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.domain.utility import UtilityBreakdown
from fortress_agent.memory.world import WorldMemory
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.team_constraints import (
    GoldBudgetConstraint,
)
from fortress_agent.protocol.codec import GameProtocolCodec


class Deadline:
    def remaining(self):
        return 10

    def expired(self):
        return False


def ctx():
    result = GameProtocolCodec().parse_state({
        "roundNo": 10,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": [],
        },
        "teamOur": {
            "type": "challenger",
            "teamId": "x",
            "teamName": "x",
            "goldNum": 10,
            "totalScore": 0,
            "playerTasks": [],
            "roles": [],
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": []},
        "weaponShopList": [
            {"name": "Medicine", "price": 10},
        ],
        "errors": [],
    })
    assert result.ok

    return PolicyContext(
        state=result.value,
        world_memory=WorldMemory().view(),
        policy_state=PolicyState.create(),
        deadline=Deadline(),
        features=MappingProxyType({}),
    )


def decision(actor, utility):
    return Decision(
        action=BuyAction(
            actor_id=actor,
            action_type="buy",
            name="Medicine",
            num=1,
        ),
        strategy_id="prepare",
        utility=UtilityBreakdown(
            total=utility
        ),
    )


def test_gold_budget_keeps_higher_utility_purchase():
    result = GoldBudgetConstraint().apply(
        ctx(),
        (
            decision(10010, 2.0),
            decision(10011, 5.0),
        ),
    )

    assert len(result.decisions) == 1
    assert (
        result.decisions[0]
        .action.actor_id
        == 10011
    )
