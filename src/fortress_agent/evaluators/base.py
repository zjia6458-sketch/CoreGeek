from __future__ import annotations

from abc import ABC, abstractmethod

from fortress_agent.domain.action import Action
from fortress_agent.domain.utility import UtilityBreakdown
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.strategy import StrategyProfile


class ActionEvaluator(ABC):
    """动作效用评估器抽象类。

    主要实现：
    - ``evaluators/basic.py``：Move/Explore/Gather/Attack/ResourceApproach；
    - ``evaluators/navigation.py``：GoalApproach；
    - ``evaluators/business.py``：Sell/Buy/Use/Task/Treasure/Build。

    Registry 要求每个 Action 恰好匹配一个 Evaluator，避免同一动作被多套
    评分逻辑同时解释。
    """

    evaluator_id: str

    @abstractmethod
    def supports(self, action: Action) -> bool:
        ...

    @abstractmethod
    def evaluate(
        self,
        ctx: PolicyContext,
        action: Action,
        strategy: StrategyProfile,
    ) -> UtilityBreakdown:
        ...


class EvaluatorRegistry:
    def __init__(self) -> None:
        self._evaluators: list[ActionEvaluator] = []
        self._ids: set[str] = set()

    def register(self, evaluator: ActionEvaluator) -> None:
        if evaluator.evaluator_id in self._ids:
            raise ValueError(
                f"duplicate evaluator: {evaluator.evaluator_id}"
            )
        self._evaluators.append(evaluator)
        self._ids.add(evaluator.evaluator_id)

    def resolve(self, action: Action) -> ActionEvaluator:
        matches = [
            evaluator
            for evaluator in self._evaluators
            if evaluator.supports(action)
        ]

        if len(matches) != 1:
            raise LookupError(
                f"expected exactly one evaluator for {type(action).__name__}, "
                f"found {[x.evaluator_id for x in matches]}"
            )

        return matches[0]
