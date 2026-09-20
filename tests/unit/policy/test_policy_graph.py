import asyncio
from dataclasses import replace
from types import MappingProxyType

import pytest

from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.memory.world import WorldMemory
from fortress_agent.observability.sinks import InMemoryTraceSink
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.graph.builder import PolicyGraphBuilder
from fortress_agent.policy.graph.engine import PolicyGraphEngine
from fortress_agent.policy.graph.function_node import FunctionPolicyNode
from fortress_agent.policy.graph.model import (
    END,
    GraphExecutionError,
    GraphValidationError,
    NodeResult,
    PolicyFrame,
)
from fortress_agent.protocol.codec import GameProtocolCodec


class FakeDeadline:
    def __init__(self):
        self.is_expired = False

    def remaining(self):
        return 10.0 if not self.is_expired else 0.0

    def expired(self):
        return self.is_expired


def make_context():
    parsed = GameProtocolCodec().parse_state({
        "round": 1,
        "day": 1,
        "phase": "day",
    })
    assert parsed.ok

    return PolicyContext(
        state=parsed.value,
        world_memory=WorldMemory().view(),
        policy_state=PolicyState(),
        deadline=FakeDeadline(),
        features=MappingProxyType({}),
    )


def test_node_outcome_not_node_implementation_decides_next_hop():
    visited = []

    async def route_node(ctx, frame):
        visited.append("route")
        return NodeResult("go", frame)

    async def node_a(ctx, frame):
        visited.append("A")
        return NodeResult("done", frame)

    async def node_b(ctx, frame):
        visited.append("B")
        return NodeResult("done", frame)

    route = FunctionPolicyNode(
        node_id="route",
        outcomes={"go"},
        func=route_node,
    )
    a = FunctionPolicyNode(
        node_id="A",
        outcomes={"done"},
        func=node_a,
    )
    b = FunctionPolicyNode(
        node_id="B",
        outcomes={"done"},
        func=node_b,
    )

    graph_a = (
        PolicyGraphBuilder()
        .add_node(route)
        .add_node(a)
        .set_entry("route")
        .add_transition("route", "go", "A")
        .add_transition("A", "done", END)
        .compile()
    )

    asyncio.run(PolicyGraphEngine(graph_a).run(make_context()))
    assert visited == ["route", "A"]

    # The same route node implementation can now be wired to B.
    # It does not import or reference A/B.
    visited.clear()

    route2 = FunctionPolicyNode(
        node_id="route",
        outcomes={"go"},
        func=route_node,
    )
    b2 = FunctionPolicyNode(
        node_id="B",
        outcomes={"done"},
        func=node_b,
    )

    graph_b = (
        PolicyGraphBuilder()
        .add_node(route2)
        .add_node(b2)
        .set_entry("route")
        .add_transition("route", "go", "B")
        .add_transition("B", "done", END)
        .compile()
    )

    asyncio.run(PolicyGraphEngine(graph_b).run(make_context()))
    assert visited == ["route", "B"]


def test_graph_compile_requires_every_declared_outcome_to_have_route():
    async def func(ctx, frame):
        return NodeResult("yes", frame)

    node = FunctionPolicyNode(
        node_id="router",
        outcomes={"yes", "no"},
        func=func,
    )

    builder = (
        PolicyGraphBuilder()
        .add_node(node)
        .set_entry("router")
        .add_transition("router", "yes", END)
    )

    with pytest.raises(GraphValidationError, match="missing transition"):
        builder.compile()


def test_graph_rejects_unreachable_node():
    async def done(ctx, frame):
        return NodeResult("done", frame)

    entry = FunctionPolicyNode(
        node_id="entry",
        outcomes={"done"},
        func=done,
    )
    orphan = FunctionPolicyNode(
        node_id="orphan",
        outcomes={"done"},
        func=done,
    )

    builder = (
        PolicyGraphBuilder()
        .add_node(entry)
        .add_node(orphan)
        .set_entry("entry")
        .add_transition("entry", "done", END)
        .add_transition("orphan", "done", END)
    )

    with pytest.raises(GraphValidationError, match="unreachable"):
        builder.compile()


def test_graph_enforces_node_visit_limit():
    async def loop(ctx, frame):
        return NodeResult("again", frame)

    node = FunctionPolicyNode(
        node_id="loop",
        outcomes={"again", "done"},
        func=loop,
        max_visits=2,
    )

    # Both outcomes must be wired. Runtime always chooses "again".
    graph = (
        PolicyGraphBuilder()
        .add_node(node)
        .set_entry("loop")
        .add_transition("loop", "again", "loop")
        .add_transition("loop", "done", END)
        .compile(max_steps=10)
    )

    with pytest.raises(GraphExecutionError, match="visit limit"):
        asyncio.run(PolicyGraphEngine(graph).run(make_context()))


def test_graph_emits_trace_with_resolved_next_node():
    async def done(ctx, frame):
        return NodeResult("done", frame)

    node = FunctionPolicyNode(
        node_id="entry",
        outcomes={"done"},
        func=done,
    )

    graph = (
        PolicyGraphBuilder()
        .add_node(node)
        .set_entry("entry")
        .add_transition("entry", "done", END)
        .compile()
    )

    trace = InMemoryTraceSink()
    asyncio.run(
        PolicyGraphEngine(graph, trace_sink=trace).run(make_context())
    )

    assert trace.events[0].node_id == "entry"
    assert trace.events[0].data["outcome"] == "done"
    assert trace.events[0].data["next_node"] == END
