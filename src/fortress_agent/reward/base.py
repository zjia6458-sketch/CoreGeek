from __future__ import annotations

from abc import ABC, abstractmethod

from fortress_agent.domain.action import Action
from fortress_agent.domain.reward import RewardBreakdown
from fortress_agent.policy.context import PolicyContext


class ExpectedRewardModel(ABC):
    """候选动作的期望 Reward 模型抽象类。

    实现分布在 ``reward/models.py``、``reward/navigation.py``、
    ``reward/business.py``。它只估计动作的业务收益/成本，最终排序还会经过
    UtilityComposer 与 StrategyProfile 权重。
    """

    model_id: str

    @abstractmethod
    def supports(self, action: Action) -> bool:
        ...

    @abstractmethod
    def estimate(
        self,
        ctx: PolicyContext,
        action: Action,
    ) -> RewardBreakdown:
        ...
