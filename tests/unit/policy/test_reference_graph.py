import asyncio
from types import MappingProxyType

from fortress_agent.domain.action import MoveAction
from fortress_agent.domain.decision import Decision
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.domain.utility import UtilityBreakdown
from fortress_agent.memory.world import WorldMemory
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.graph.engine import PolicyGraphEngine
from fortress_agent.policy.graph.reference import (
    ReferencePolicyServices,
    build_reference_policy_graph,
)
from fortress_agent.protocol.codec import GameProtocolCodec


class Deadline:
    def remaining(self):
        return 10.0

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
        policy_state=PolicyState(version=9),
        deadline=Deadline(),
        features=MappingProxyType({}),
    )


class Runtime:
    def __init__(self, mode="FULL"):
        self.value = mode
    def mode(self, ctx):
        return self.value


class Strategy:
    def select(self, ctx):
        return "expand"


class Candidates:
    def __init__(self, empty=False):
        self.empty = empty
    def generate(self, ctx, strategy):
        if self.empty:
            return ()
        return (
            MoveAction(
                actor_id=1,
                action_type="move",
                x=1,
                y=2,
            ),
        )


class Legal:
    def filter(self, ctx, actions):
        return actions


class Rules:
    def apply(self, ctx, actions):
        return actions, ("basic-rule",), ()


class Ranker:
    def select(self, ctx, actions, strategy):
        if not actions:
            return None
        return actions[0], UtilityBreakdown(total=10.0)


class Validator:
    def __init__(self, valid=True):
        self._valid = valid
    def valid(self, ctx, action):
        return self._valid


class Emergency:
    def select(self, ctx):
        return (
            MoveAction(
                actor_id=99,
                action_type="move",
                x=0,
                y=0,
            ),
            UtilityBreakdown(total=-1.0),
        )


class DecisionBuilder:
    def build(self, ctx, frame):
        return Decision(
            action=frame.selected_action,
            strategy_id=str(frame.strategy or "emergency"),
            utility=frame.selected_utility,
            matched_rules=frame.matched_rules,
            rejected_reasons=frame.rejected_reasons,
            policy_version=ctx.policy_state.version,
        )


def services(*, runtime="FULL", empty=False, valid=True):
    return ReferencePolicyServices(
        runtime=Runtime(runtime),
        strategy=Strategy(),
        candidates=Candidates(empty),
        legal=Legal(),
        rules=Rules(),
        ranker=Ranker(),
        validator=Validator(valid),
        emergency=Emergency(),
        decision=DecisionBuilder(),
    )


def test_normal_route_reaches_final_decision():
    graph = build_reference_policy_graph(services())
    frame = asyncio.run(PolicyGraphEngine(graph).run(ctx()))

    assert frame.decision is not None
    assert frame.decision.action.actor_id == 1
    assert frame.decision.utility.total == 10.0


def test_empty_candidates_route_to_emergency():
    graph = build_reference_policy_graph(services(empty=True))
    frame = asyncio.run(PolicyGraphEngine(graph).run(ctx()))

    assert frame.decision.action.actor_id == 99


def test_invalid_selected_action_routes_to_emergency():
    graph = build_reference_policy_graph(services(valid=False))
    frame = asyncio.run(PolicyGraphEngine(graph).run(ctx()))

    assert frame.decision.action.actor_id == 99


def test_runtime_emergency_skips_normal_policy():
    graph = build_reference_policy_graph(
        services(runtime="EMERGENCY")
    )
    frame = asyncio.run(PolicyGraphEngine(graph).run(ctx()))

    assert frame.runtime_mode == "EMERGENCY"
    assert frame.decision.action.actor_id == 99
