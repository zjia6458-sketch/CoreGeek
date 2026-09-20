from types import MappingProxyType

from fortress_agent.domain.action import GatherAction, MoveAction
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.memory.world import WorldMemory
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.legal import BasicLegalActionFilter
from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.rules.base import BasicRuleEngine, RuleRegistry
from fortress_agent.rules.basic import (
    GatherOnlyDuringDayRule,
    GatherWorkerOnlyRule,
)


class Deadline:
    def remaining(self):
        return 10.0
    def expired(self):
        return False


def ctx(*, phase="day", role="worker"):
    parsed = GameProtocolCodec().parse_state({
        "round": 1,
        "day": 1,
        "phase": phase,
        "characters": [{
            "id": 1,
            "role": role,
            "hp": 220,
            "position": {"x": 5, "y": 5},
        }],
    })
    assert parsed.ok

    memory = WorldMemory()
    memory.resources.discover(
        resource_id="iron",
        resource_type="iron",
        x=5,
        y=5,
        amount=100,
        round_id=1,
    )

    return PolicyContext(
        state=parsed.value,
        world_memory=memory.view(),
        policy_state=PolicyState(),
        deadline=Deadline(),
        features=MappingProxyType({}),
    )


def test_legal_filter_rejects_non_adjacent_move():
    action = MoveAction(
        actor_id=1,
        action_type="move",
        x=10,
        y=10,
    )
    assert not BasicLegalActionFilter().is_legal(
        ctx(),
        action,
    )


def test_legal_filter_rejects_gather_at_night():
    action = GatherAction(
        actor_id=1,
        action_type="gather",
        resource_id="iron",
    )
    assert not BasicLegalActionFilter().is_legal(
        ctx(phase="night"),
        action,
    )


def test_rule_engine_rejects_non_worker_gather():
    registry = RuleRegistry()
    registry.register(GatherOnlyDuringDayRule())
    registry.register(GatherWorkerOnlyRule())

    action = GatherAction(
        actor_id=1,
        action_type="gather",
        resource_id="iron",
    )

    viable, matched, rejected = BasicRuleEngine(
        registry
    ).apply(
        ctx(role="pioneer"),
        (action,),
    )

    assert viable == ()
    assert "gather_worker_only" in matched
    assert rejected
