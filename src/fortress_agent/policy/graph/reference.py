from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fortress_agent.domain.action import Action
from fortress_agent.domain.decision import Decision
from fortress_agent.domain.utility import UtilityBreakdown
from fortress_agent.policy.context import PolicyContext

from .builder import PolicyGraphBuilder
from .model import END, NodeResult, PolicyFrame, PolicyNode


class RuntimeModeResolver(Protocol):
    def mode(self, ctx: PolicyContext) -> str:
        ...


class StrategyService(Protocol):
    def select(self, ctx: PolicyContext) -> object:
        ...


class CandidateService(Protocol):
    def generate(
        self,
        ctx: PolicyContext,
        strategy: object,
    ) -> tuple[Action, ...]:
        ...


class LegalFilterService(Protocol):
    def filter(
        self,
        ctx: PolicyContext,
        actions: tuple[Action, ...],
    ) -> tuple[Action, ...]:
        ...


class RuleService(Protocol):
    def apply(
        self,
        ctx: PolicyContext,
        actions: tuple[Action, ...],
    ) -> tuple[tuple[Action, ...], tuple[str, ...], tuple[str, ...]]:
        ...


class RankService(Protocol):
    def select(
        self,
        ctx: PolicyContext,
        actions: tuple[Action, ...],
        strategy: object,
    ) -> tuple[Action, UtilityBreakdown] | None:
        ...


class ValidationService(Protocol):
    def valid(self, ctx: PolicyContext, action: Action) -> bool:
        ...


class EmergencyService(Protocol):
    def select(
        self,
        ctx: PolicyContext,
    ) -> tuple[Action, UtilityBreakdown]:
        ...


class DecisionService(Protocol):
    def build(
        self,
        ctx: PolicyContext,
        frame: PolicyFrame,
    ) -> Decision:
        ...


@dataclass(slots=True)
class ReferencePolicyServices:
    runtime: RuntimeModeResolver
    strategy: StrategyService
    candidates: CandidateService
    legal: LegalFilterService
    rules: RuleService
    ranker: RankService
    validator: ValidationService
    emergency: EmergencyService
    decision: DecisionService


class RuntimeGateNode(PolicyNode):
    node_id = "runtime_gate"
    outcomes = frozenset({"normal", "emergency"})

    def __init__(self, service: RuntimeModeResolver) -> None:
        self._service = service

    async def execute(self, ctx, frame):
        mode = self._service.mode(ctx).upper()

        if mode == "EMERGENCY":
            return NodeResult(
                "emergency",
                frame.with_updates(runtime_mode=mode),
            )

        return NodeResult(
            "normal",
            frame.with_updates(runtime_mode=mode),
        )


class StrategyNode(PolicyNode):
    node_id = "strategy"
    outcomes = frozenset({"selected"})

    def __init__(self, service: StrategyService) -> None:
        self._service = service

    async def execute(self, ctx, frame):
        strategy = self._service.select(ctx)
        return NodeResult(
            "selected",
            frame.with_updates(strategy=strategy),
        )


class CandidateNode(PolicyNode):
    node_id = "candidates"
    outcomes = frozenset({"available", "empty"})

    def __init__(self, service: CandidateService) -> None:
        self._service = service

    async def execute(self, ctx, frame):
        actions = self._service.generate(ctx, frame.strategy)
        outcome = "available" if actions else "empty"
        return NodeResult(
            outcome,
            frame.with_updates(candidates=actions),
        )


class LegalFilterNode(PolicyNode):
    node_id = "legal_filter"
    outcomes = frozenset({"available", "empty"})

    def __init__(self, service: LegalFilterService) -> None:
        self._service = service

    async def execute(self, ctx, frame):
        actions = self._service.filter(ctx, frame.candidates)
        outcome = "available" if actions else "empty"
        return NodeResult(
            outcome,
            frame.with_updates(legal_actions=actions),
        )


class RuleNode(PolicyNode):
    node_id = "rules"
    outcomes = frozenset({"available", "empty"})

    def __init__(self, service: RuleService) -> None:
        self._service = service

    async def execute(self, ctx, frame):
        actions, matched, rejected = self._service.apply(
            ctx,
            frame.legal_actions,
        )
        outcome = "available" if actions else "empty"
        return NodeResult(
            outcome,
            frame.with_updates(
                viable_actions=actions,
                matched_rules=matched,
                rejected_reasons=rejected,
            ),
        )


class RankNode(PolicyNode):
    node_id = "rank"
    outcomes = frozenset({"selected", "empty"})

    def __init__(self, service: RankService) -> None:
        self._service = service

    async def execute(self, ctx, frame):
        selected = self._service.select(
            ctx,
            frame.viable_actions,
            frame.strategy,
        )

        if selected is None:
            return NodeResult("empty", frame)

        action, utility = selected
        return NodeResult(
            "selected",
            frame.with_updates(
                selected_action=action,
                selected_utility=utility,
            ),
        )


class ValidateNode(PolicyNode):
    node_id = "validate"
    outcomes = frozenset({"valid", "invalid"})

    def __init__(self, service: ValidationService) -> None:
        self._service = service

    async def execute(self, ctx, frame):
        assert frame.selected_action is not None
        outcome = (
            "valid"
            if self._service.valid(ctx, frame.selected_action)
            else "invalid"
        )
        return NodeResult(outcome, frame)


class EmergencyNode(PolicyNode):
    node_id = "emergency"
    outcomes = frozenset({"selected"})
    # Multiple failure branches may converge here, but it should execute once
    # in any single run.
    max_visits = 1

    def __init__(self, service: EmergencyService) -> None:
        self._service = service

    async def execute(self, ctx, frame):
        action, utility = self._service.select(ctx)
        return NodeResult(
            "selected",
            frame.with_updates(
                selected_action=action,
                selected_utility=utility,
            ),
        )


class FinalizeNode(PolicyNode):
    node_id = "finalize"
    outcomes = frozenset({"done"})

    def __init__(self, service: DecisionService) -> None:
        self._service = service

    async def execute(self, ctx, frame):
        decision = self._service.build(ctx, frame)
        return NodeResult(
            "done",
            frame.with_updates(decision=decision),
        )


def build_reference_policy_graph(
    services: ReferencePolicyServices,
    *,
    max_steps: int = 16,
):
    """Reference topology.

    Nodes return semantic outcomes only. Topology decides the next hop.
    Adding/replacing a node therefore changes this builder/graph config,
    not the node implementation or the graph engine.
    """
    builder = PolicyGraphBuilder()

    for node in (
        RuntimeGateNode(services.runtime),
        StrategyNode(services.strategy),
        CandidateNode(services.candidates),
        LegalFilterNode(services.legal),
        RuleNode(services.rules),
        RankNode(services.ranker),
        ValidateNode(services.validator),
        EmergencyNode(services.emergency),
        FinalizeNode(services.decision),
    ):
        builder.add_node(node)

    builder.set_entry("runtime_gate")

    builder.add_transition("runtime_gate", "normal", "strategy")
    builder.add_transition("runtime_gate", "emergency", "emergency")

    builder.add_transition("strategy", "selected", "candidates")

    builder.add_transition("candidates", "available", "legal_filter")
    builder.add_transition("candidates", "empty", "emergency")

    builder.add_transition("legal_filter", "available", "rules")
    builder.add_transition("legal_filter", "empty", "emergency")

    builder.add_transition("rules", "available", "rank")
    builder.add_transition("rules", "empty", "emergency")

    builder.add_transition("rank", "selected", "validate")
    builder.add_transition("rank", "empty", "emergency")

    builder.add_transition("validate", "valid", "finalize")
    builder.add_transition("validate", "invalid", "emergency")

    builder.add_transition("emergency", "selected", "finalize")
    builder.add_transition("finalize", "done", END)

    return builder.compile(max_steps=max_steps)
