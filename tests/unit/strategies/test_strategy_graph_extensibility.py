from types import MappingProxyType

from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.memory.world import WorldMemory
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.strategy import StrategyProfile
from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.strategies.graph import (
    GraphStrategySelector,
    StrategyActivation,
    StrategyActivator,
    StrategyActivatorRegistry,
    StrategyGraphBuilder,
    StrategyGraphRegistry,
    StrategyNode,
    StrategyNodeResult,
)


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
        policy_state=PolicyState.create(),
        deadline=Deadline(),
        features=MappingProxyType({}),
    )


class AlwaysActivator(StrategyActivator):
    activator_id = "always"

    def activate(self, ctx):
        return StrategyActivation(
            graph_id="custom",
            score=1.0,
            priority=1,
            reason="test custom graph",
        )


class PersistentNode(StrategyNode):
    node_id = "persistent"

    def run(self, ctx, session):
        visits = int(
            session.data.get(
                "visits",
                0,
            )
        )

        profile = StrategyProfile(
            strategy_id=(
                "first_visit"
                if visits == 0
                else "later_visit"
            ),
            candidate_tags=frozenset(
                {"explore"}
            ),
        )

        return StrategyNodeResult(
            outcome="done",
            profile=profile,
            state_updates={
                "visits": visits + 1,
            },
        )


def test_new_complex_strategy_requires_only_graph_and_activator_registration():
    graphs = StrategyGraphRegistry()
    graphs.register(
        StrategyGraphBuilder(
            "custom",
            "persistent",
        )
        .add_node(PersistentNode())
        .route(
            "persistent",
            "done",
            "__END__",
        )
        .build()
    )

    activators = StrategyActivatorRegistry()
    activators.register(
        AlwaysActivator()
    )

    selector = GraphStrategySelector(
        graphs=graphs,
        activators=activators,
    )

    first = selector.select(ctx())
    second = selector.select(ctx())

    assert first.strategy_id == "first_visit"
    assert second.strategy_id == "later_visit"

    assert (
        second.metadata[
            "strategy_graph"
        ]
        == "custom"
    )
    assert (
        second.metadata[
            "strategy_session_version"
        ]
        >= 2
    )
