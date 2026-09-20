from __future__ import annotations

from fortress_agent.domain.action import Action
from fortress_agent.domain.reward import RewardBreakdown
from fortress_agent.policy.context import PolicyContext

from .base import ExpectedRewardModel


class RewardModelRegistry:
    def __init__(self) -> None:
        self._models: list[ExpectedRewardModel] = []
        self._ids: set[str] = set()

    def register(self, model: ExpectedRewardModel) -> None:
        if model.model_id in self._ids:
            raise ValueError(f"duplicate reward model: {model.model_id}")
        self._models.append(model)
        self._ids.add(model.model_id)

    def resolve(self, action: Action) -> ExpectedRewardModel:
        matches = [model for model in self._models if model.supports(action)]

        if not matches:
            raise LookupError(
                f"no reward model supports action type {type(action).__name__}"
            )

        if len(matches) > 1:
            raise LookupError(
                f"multiple reward models support action type "
                f"{type(action).__name__}: "
                f"{[model.model_id for model in matches]}"
            )

        return matches[0]

    def estimate(
        self,
        ctx: PolicyContext,
        action: Action,
    ) -> RewardBreakdown:
        reward = self.resolve(action).estimate(ctx, action)

        if not reward.is_finite():
            raise ValueError(
                f"reward model returned non-finite reward for {action}"
            )

        return reward
