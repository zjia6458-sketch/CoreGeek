from __future__ import annotations

from fortress_agent.domain.action import AttackAction, ExploreAction, GatherAction, MoveAction, ResourceApproachAction
from fortress_agent.reward.engine import RewardModelRegistry
from fortress_agent.reward.utility import UtilityComposer

from .base import ActionEvaluator


class _RewardBackedEvaluator(ActionEvaluator):
    action_type = object

    def __init__(
        self,
        reward_models: RewardModelRegistry,
        composer: UtilityComposer,
    ) -> None:
        self._rewards = reward_models
        self._composer = composer

    def supports(self, action) -> bool:
        return type(action) is self.action_type

    def evaluate(self, ctx, action, strategy):
        reward = self._rewards.estimate(ctx, action)
        utility = self._composer.compose(
            ctx,
            strategy,
            reward,
        )

        if not utility.is_finite():
            raise ValueError(
                f"{self.evaluator_id} returned non-finite utility"
            )

        return utility


class MoveEvaluator(_RewardBackedEvaluator):
    evaluator_id = "move"
    action_type = MoveAction


class ResourceApproachEvaluator(_RewardBackedEvaluator):
    evaluator_id = "resource_approach"
    action_type = ResourceApproachAction


class ExplorationEvaluator(_RewardBackedEvaluator):
    evaluator_id = "exploration"
    action_type = ExploreAction


class GatherEvaluator(_RewardBackedEvaluator):
    evaluator_id = "gather"
    action_type = GatherAction


class AttackEvaluator(_RewardBackedEvaluator):
    evaluator_id = "attack"
    action_type = AttackAction
