from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Mapping

from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.strategy import StrategyProfile


@dataclass(frozen=True, slots=True)
class StrategySessionView:
    graph_id: str
    version: int
    data: Mapping[str, object]


class StrategySessionStore:
    """Small cross-turn blackboard for strategy execution.

    This is intentionally separate from PolicyState:
      - PolicyState = learned/versioned policy parameters;
      - StrategySession = temporary progress of a multi-round plan.
    """

    def __init__(self) -> None:
        self._versions: dict[str, int] = {}
        self._data: dict[str, dict[str, object]] = {}

    def view(
        self,
        graph_id: str,
    ) -> StrategySessionView:
        return StrategySessionView(
            graph_id=graph_id,
            version=self._versions.get(
                graph_id,
                0,
            ),
            data=MappingProxyType(
                dict(
                    self._data.get(
                        graph_id,
                        {},
                    )
                )
            ),
        )

    def patch(
        self,
        graph_id: str,
        updates: Mapping[str, object],
    ) -> None:
        if not updates:
            return

        data = self._data.setdefault(
            graph_id,
            {},
        )
        data.update(updates)
        self._versions[graph_id] = (
            self._versions.get(
                graph_id,
                0,
            )
            + 1
        )

    def clear(
        self,
        graph_id: str,
    ) -> None:
        self._data.pop(
            graph_id,
            None,
        )
        self._versions[graph_id] = (
            self._versions.get(
                graph_id,
                0,
            )
            + 1
        )


@dataclass(frozen=True, slots=True)
class StrategyNodeResult:
    outcome: str
    profile: StrategyProfile | None = None
    annotations: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
    state_updates: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
    clear_session: bool = False


class StrategyNode(ABC):
    """跨回合 StrategyGraph 节点抽象类。

    参考实现位于 ``strategies/reference.py`` 的 FixedProfileNode 与
    LongHorizonDecisionNode。与 PolicyNode 不同，StrategyNode 负责较长时间尺度的
    战略状态推进，输出 StrategyProfile 给当回合 PolicyGraph 使用。
    """

    node_id: str

    @abstractmethod
    def run(
        self,
        ctx: PolicyContext,
        session: StrategySessionView,
    ) -> StrategyNodeResult:
        ...


@dataclass(frozen=True, slots=True)
class StrategyGraph:
    graph_id: str
    entry_node: str
    nodes: Mapping[str, StrategyNode]
    transitions: Mapping[tuple[str, str], str]
    max_steps: int = 32

    def __post_init__(self) -> None:
        if self.entry_node not in self.nodes:
            raise ValueError(
                f"entry node not registered: {self.entry_node}"
            )

        for (source, _), target in self.transitions.items():
            if source not in self.nodes:
                raise ValueError(
                    f"transition source not registered: {source}"
                )
            if (
                target != "__END__"
                and target not in self.nodes
            ):
                raise ValueError(
                    f"transition target not registered: {target}"
                )


class StrategyGraphBuilder:
    def __init__(
        self,
        graph_id: str,
        entry_node: str,
    ) -> None:
        self._graph_id = graph_id
        self._entry = entry_node
        self._nodes: dict[str, StrategyNode] = {}
        self._transitions: dict[
            tuple[str, str],
            str,
        ] = {}

    def add_node(
        self,
        node: StrategyNode,
    ) -> "StrategyGraphBuilder":
        if node.node_id in self._nodes:
            raise ValueError(
                f"duplicate strategy node: {node.node_id}"
            )
        self._nodes[node.node_id] = node
        return self

    def route(
        self,
        source: str,
        outcome: str,
        target: str,
    ) -> "StrategyGraphBuilder":
        key = (source, outcome)
        if key in self._transitions:
            raise ValueError(
                f"duplicate transition: {source}/{outcome}"
            )
        self._transitions[key] = target
        return self

    def build(self) -> StrategyGraph:
        return StrategyGraph(
            graph_id=self._graph_id,
            entry_node=self._entry,
            nodes=MappingProxyType(
                dict(self._nodes)
            ),
            transitions=MappingProxyType(
                dict(self._transitions)
            ),
        )


@dataclass(frozen=True, slots=True)
class StrategyGraphExecution:
    graph_id: str
    profile: StrategyProfile
    visited_nodes: tuple[str, ...]
    outcomes: tuple[str, ...]
    session_version: int


class StrategyGraphEngine:
    def __init__(
        self,
        sessions: StrategySessionStore | None = None,
    ) -> None:
        self._sessions = (
            sessions
            or StrategySessionStore()
        )

    def run(
        self,
        graph: StrategyGraph,
        ctx: PolicyContext,
    ) -> StrategyGraphExecution:
        node_id = graph.entry_node
        visited: list[str] = []
        outcomes: list[str] = []

        for _ in range(graph.max_steps):
            session = self._sessions.view(
                graph.graph_id
            )
            node = graph.nodes[node_id]
            result = node.run(
                ctx,
                session,
            )

            visited.append(node_id)
            outcomes.append(result.outcome)

            if result.clear_session:
                self._sessions.clear(
                    graph.graph_id
                )
            else:
                self._sessions.patch(
                    graph.graph_id,
                    result.state_updates,
                )

            next_node = graph.transitions.get(
                (
                    node_id,
                    result.outcome,
                )
            )

            if next_node is None:
                raise RuntimeError(
                    "strategy graph has no transition for "
                    f"({node_id!r}, {result.outcome!r})"
                )

            if next_node == "__END__":
                if result.profile is None:
                    raise RuntimeError(
                        f"terminal strategy node "
                        f"{node_id!r} did not return "
                        "a StrategyProfile"
                    )

                return StrategyGraphExecution(
                    graph_id=graph.graph_id,
                    profile=result.profile,
                    visited_nodes=tuple(visited),
                    outcomes=tuple(outcomes),
                    session_version=(
                        self._sessions.view(
                            graph.graph_id
                        ).version
                    ),
                )

            node_id = next_node

        raise RuntimeError(
            f"strategy graph exceeded "
            f"max_steps={graph.max_steps}"
        )

    @property
    def sessions(self) -> StrategySessionStore:
        return self._sessions


class StrategyGraphRegistry:
    def __init__(self) -> None:
        self._graphs: dict[
            str,
            StrategyGraph,
        ] = {}

    def register(
        self,
        graph: StrategyGraph,
    ) -> None:
        if graph.graph_id in self._graphs:
            raise ValueError(
                f"duplicate strategy graph: "
                f"{graph.graph_id}"
            )
        self._graphs[
            graph.graph_id
        ] = graph

    def get(
        self,
        graph_id: str,
    ) -> StrategyGraph:
        try:
            return self._graphs[
                graph_id
            ]
        except KeyError as exc:
            raise LookupError(
                f"unknown strategy graph: "
                f"{graph_id}"
            ) from exc

    def ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(self._graphs)
        )


@dataclass(frozen=True, slots=True)
class StrategyActivation:
    graph_id: str
    score: float
    priority: int
    reason: str


class StrategyActivator(ABC):
    """选择某个 StrategyGraph 是否应被激活的抽象类。

    参考实现位于 ``strategies/reference.py``：NightActivator、PrepareActivator、
    ActiveTaskActivator、DayDefaultActivator。Activator 只负责“选哪个战略图”，
    不负责图内部状态推进。
    """

    activator_id: str

    @abstractmethod
    def activate(
        self,
        ctx: PolicyContext,
    ) -> StrategyActivation | None:
        ...


class StrategyActivatorRegistry:
    def __init__(self) -> None:
        self._activators: dict[
            str,
            StrategyActivator,
        ] = {}

    def register(
        self,
        activator: StrategyActivator,
    ) -> None:
        if (
            activator.activator_id
            in self._activators
        ):
            raise ValueError(
                f"duplicate strategy activator: "
                f"{activator.activator_id}"
            )
        self._activators[
            activator.activator_id
        ] = activator

    def choose(
        self,
        ctx: PolicyContext,
    ) -> StrategyActivation:
        candidates = [
            activation
            for _, activator in sorted(
                self._activators.items()
            )
            if (
                activation
                := activator.activate(ctx)
            ) is not None
        ]

        if not candidates:
            raise RuntimeError(
                "no strategy activator matched "
                "current context"
            )

        candidates.sort(
            key=lambda item: (
                -item.priority,
                -item.score,
                item.graph_id,
            )
        )
        return candidates[0]


class GraphStrategySelector:
    def __init__(
        self,
        *,
        graphs: StrategyGraphRegistry,
        activators: StrategyActivatorRegistry,
        engine: StrategyGraphEngine | None = None,
    ) -> None:
        self._graphs = graphs
        self._activators = activators
        self._engine = (
            engine
            or StrategyGraphEngine()
        )

    def select(
        self,
        ctx: PolicyContext,
    ) -> StrategyProfile:
        activation = (
            self._activators.choose(ctx)
        )
        execution = self._engine.run(
            self._graphs.get(
                activation.graph_id
            ),
            ctx,
        )

        metadata = dict(
            execution.profile.metadata
        )
        metadata.update({
            "strategy_graph": (
                execution.graph_id
            ),
            "strategy_activation_reason": (
                activation.reason
            ),
            "strategy_visited_nodes": (
                execution.visited_nodes
            ),
            "strategy_outcomes": (
                execution.outcomes
            ),
            "strategy_session_version": (
                execution.session_version
            ),
        })

        return replace(
            execution.profile,
            metadata=MappingProxyType(
                metadata
            ),
        )

    def explain(
        self,
        ctx: PolicyContext,
    ) -> StrategyGraphExecution:
        activation = (
            self._activators.choose(ctx)
        )
        return self._engine.run(
            self._graphs.get(
                activation.graph_id
            ),
            ctx,
        )

    @property
    def sessions(self) -> StrategySessionStore:
        return self._engine.sessions
