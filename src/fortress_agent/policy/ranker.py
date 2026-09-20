from __future__ import annotations

from fortress_agent.evaluators.base import EvaluatorRegistry
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.strategy import StrategyProfile


class RewardAwareRanker:
    def __init__(self, evaluators: EvaluatorRegistry) -> None:
        self._evaluators = evaluators

    def rank_all(
        self,
        ctx: PolicyContext,
        actions: tuple,
        strategy: StrategyProfile,
    ):
        """返回全部候选的稳定排序，供 TeamPlanner 在冲突后尝试次优动作。"""
        ranked = []
        for action in actions:
            evaluator = self._evaluators.resolve(action)
            utility = evaluator.evaluate(ctx, action, strategy)
            ranked.append((action, utility))
        ranked.sort(
            key=lambda item: (
                -item[1].total,
                item[1].risk,
                repr(item[0]),
            )
        )
        return tuple(ranked)

    def select(
        self,
        ctx: PolicyContext,
        actions: tuple,
        strategy: StrategyProfile,
    ):
        ranked = self.rank_all(ctx, actions, strategy)
        return ranked[0] if ranked else None
