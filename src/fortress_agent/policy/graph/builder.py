from __future__ import annotations

from collections import defaultdict, deque

from .engine import CompiledPolicyGraph
from .model import END, GraphValidationError, PolicyNode


class PolicyGraphBuilder:
    def __init__(self) -> None:
        self._nodes: dict[str, PolicyNode] = {}
        self._transitions: dict[tuple[str, str], str] = {}
        self._entry_node: str | None = None

    def add_node(self, node: PolicyNode) -> "PolicyGraphBuilder":
        if node.node_id in self._nodes:
            raise GraphValidationError(f"duplicate node id: {node.node_id}")
        self._nodes[node.node_id] = node
        return self

    def set_entry(self, node_id: str) -> "PolicyGraphBuilder":
        self._entry_node = node_id
        return self

    def add_transition(
        self,
        from_node: str,
        outcome: str,
        to_node: str,
    ) -> "PolicyGraphBuilder":
        key = (from_node, outcome)

        if key in self._transitions:
            raise GraphValidationError(
                f"duplicate transition: {from_node}[{outcome}]"
            )

        self._transitions[key] = to_node
        return self

    def compile(
        self,
        *,
        max_steps: int = 32,
    ) -> CompiledPolicyGraph:
        if self._entry_node is None:
            raise GraphValidationError("entry node is not set")

        if self._entry_node not in self._nodes:
            raise GraphValidationError(
                f"entry node does not exist: {self._entry_node}"
            )

        for (from_node, outcome), to_node in self._transitions.items():
            if from_node not in self._nodes:
                raise GraphValidationError(
                    f"transition source does not exist: {from_node}"
                )

            if to_node != END and to_node not in self._nodes:
                raise GraphValidationError(
                    f"transition target does not exist: {to_node}"
                )

            node = self._nodes[from_node]
            if outcome not in node.outcomes:
                raise GraphValidationError(
                    f"node {from_node} does not declare outcome {outcome!r}"
                )

        # Every declared outcome must have an explicit route.
        # This intentionally avoids silent wildcard fallbacks.
        for node_id, node in self._nodes.items():
            for outcome in node.outcomes:
                if (node_id, outcome) not in self._transitions:
                    raise GraphValidationError(
                        f"missing transition for {node_id}[{outcome}]"
                    )

        reachable = self._reachable_nodes(self._entry_node)

        unreachable = set(self._nodes) - reachable
        if unreachable:
            raise GraphValidationError(
                f"unreachable nodes: {sorted(unreachable)}"
            )

        if not any(
            source in reachable and target == END
            for (source, _), target in self._transitions.items()
        ):
            raise GraphValidationError("graph has no reachable END transition")

        return CompiledPolicyGraph(
            nodes=dict(self._nodes),
            transitions=dict(self._transitions),
            entry_node=self._entry_node,
            max_steps=max_steps,
        )

    def _reachable_nodes(self, entry: str) -> set[str]:
        outgoing: dict[str, list[str]] = defaultdict(list)

        for (source, _), target in self._transitions.items():
            if target != END:
                outgoing[source].append(target)

        seen: set[str] = set()
        queue = deque([entry])

        while queue:
            node = queue.popleft()

            if node in seen:
                continue

            seen.add(node)

            for target in outgoing[node]:
                if target not in seen:
                    queue.append(target)

        return seen
