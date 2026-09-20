from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import Any

from fortress_agent.domain.action import Action
from fortress_agent.domain.decision import Decision
from fortress_agent.domain.utility import UtilityBreakdown
from fortress_agent.policy.context import PolicyContext


END = "__END__"


class GraphValidationError(ValueError):
    pass


class GraphExecutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PolicyFrame:
    runtime_mode: str | None = None
    strategy: object | None = None

    candidates: tuple[Action, ...] = ()
    legal_actions: tuple[Action, ...] = ()
    viable_actions: tuple[Action, ...] = ()

    selected_action: Action | None = None
    selected_utility: UtilityBreakdown | None = None

    matched_rules: tuple[str, ...] = ()
    rejected_reasons: tuple[str, ...] = ()

    decision: Decision | None = None
    # 本回合实际经过的 PolicyGraph 节点链。仅用于可观测性/复盘，
    # 不参与策略判断，因此 Logger 模式不会改变它的生成逻辑。
    node_chain: tuple[str, ...] = ()

    def with_updates(self, **updates: Any) -> "PolicyFrame":
        return replace(self, **updates)


@dataclass(frozen=True, slots=True)
class NodeResult:
    outcome: str
    frame: PolicyFrame


class PolicyNode(ABC):
    """PolicyGraph 节点抽象类：节点只返回语义 outcome，不决定下一跳。

    主要实现位于 ``policy/graph/reference.py``：RuntimeGateNode、StrategyNode、
    CandidateNode、LegalFilterNode、RuleNode、RankNode、ValidateNode、
    EmergencyNode、FinalizeNode。拓扑统一由 ``build_reference_policy_graph``
    声明，保持“节点逻辑”和“流程连接”分离。
    """

    node_id: str
    outcomes: frozenset[str]
    max_visits: int = 1

    @abstractmethod
    async def execute(
        self,
        ctx: PolicyContext,
        frame: PolicyFrame,
    ) -> NodeResult:
        ...
