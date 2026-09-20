from __future__ import annotations

from collections.abc import Awaitable, Callable

from fortress_agent.policy.context import PolicyContext

from .model import NodeResult, PolicyFrame, PolicyNode


NodeFunction = Callable[
    [PolicyContext, PolicyFrame],
    Awaitable[NodeResult],
]


class FunctionPolicyNode(PolicyNode):
    def __init__(
        self,
        *,
        node_id: str,
        outcomes: set[str] | frozenset[str],
        func: NodeFunction,
        max_visits: int = 1,
    ) -> None:
        self.node_id = node_id
        self.outcomes = frozenset(outcomes)
        self._func = func
        self.max_visits = max_visits

    async def execute(
        self,
        ctx: PolicyContext,
        frame: PolicyFrame,
    ) -> NodeResult:
        return await self._func(ctx, frame)
