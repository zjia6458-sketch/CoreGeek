from __future__ import annotations

from collections import defaultdict
import asyncio
import time

from fortress_agent.observability.trace import TraceEvent, TraceSink
from fortress_agent.policy.context import PolicyContext

from .model import (
    END,
    GraphExecutionError,
    NodeResult,
    PolicyFrame,
    PolicyNode,
)


class _NullTraceSink(TraceSink):
    def emit(self, event: TraceEvent) -> None:
        pass


class CompiledPolicyGraph:
    def __init__(
        self,
        *,
        nodes: dict[str, PolicyNode],
        transitions: dict[tuple[str, str], str],
        entry_node: str,
        max_steps: int,
    ) -> None:
        self.nodes = nodes
        self.transitions = transitions
        self.entry_node = entry_node
        self.max_steps = max_steps


class PolicyGraphEngine:
    def __init__(
        self,
        graph: CompiledPolicyGraph,
        *,
        trace_sink: TraceSink | None = None,
    ) -> None:
        self._graph = graph
        self._trace = trace_sink or _NullTraceSink()

    async def run(
        self,
        ctx: PolicyContext,
        *,
        initial_frame: PolicyFrame | None = None,
    ) -> PolicyFrame:
        current = self._graph.entry_node
        frame = initial_frame or PolicyFrame()
        visits: dict[str, int] = defaultdict(int)

        for step in range(self._graph.max_steps):
            # PolicyNode 的 execute() 大多是同步 CPU 逻辑包在 async 函数中。
            # 主动让出一次事件循环，才能让 HTTP 外层的 asyncio timeout
            # 在节点之间真正获得取消机会。
            await asyncio.sleep(0)

            if ctx.deadline.expired():
                raise GraphExecutionError(
                    f"deadline expired before node {current}"
                )

            node = self._graph.nodes[current]

            visits[current] += 1
            if visits[current] > node.max_visits:
                raise GraphExecutionError(
                    f"node visit limit exceeded: {current}"
                )

            started = time.monotonic()

            result = await node.execute(ctx, frame)

            # 再次让出事件循环：若某个节点已经消耗了大部分预算，外层
            # watchdog 可以在进入下一节点之前及时终止本轮复杂决策。
            await asyncio.sleep(0)

            if result.outcome not in node.outcomes:
                raise GraphExecutionError(
                    f"node {current} returned undeclared outcome "
                    f"{result.outcome!r}"
                )

            next_node = self._graph.transitions.get(
                (current, result.outcome)
            )

            if next_node is None:
                # Compile should make this impossible. Keeping runtime guard
                # protects against corrupted/dynamically replaced graphs.
                raise GraphExecutionError(
                    f"no transition for {current}[{result.outcome}]"
                )

            elapsed_ms = (time.monotonic() - started) * 1000.0

            self._trace.emit(
                TraceEvent(
                    kind="policy_node_completed",
                    round_id=ctx.state.round_id,
                    node_id=current,
                    data={
                        "outcome": result.outcome,
                        "next_node": next_node,
                        "step": step,
                        "latency_ms": elapsed_ms,
                    },
                    correlation_id=ctx.correlation_id,
                    event_id=(
                        f"{ctx.correlation_id}:policy:{step}:{current}"
                        if ctx.correlation_id
                        else None
                    ),
                )
            )

            frame = result.frame.with_updates(
                node_chain=(*result.frame.node_chain, current),
            )

            if next_node == END:
                return frame

            current = next_node

        raise GraphExecutionError(
            f"graph exceeded max_steps={self._graph.max_steps}"
        )
