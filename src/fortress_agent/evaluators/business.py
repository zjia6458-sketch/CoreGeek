from __future__ import annotations

from fortress_agent.domain.action import (
    AcceptTaskAction,
    BuildAction,
    BuyAction,
    SellAction,
    SubmitAnswerAction,
    SummonTreasureAction,
    UseAction,
)

from .basic import _RewardBackedEvaluator


class SellEvaluator(_RewardBackedEvaluator):
    evaluator_id = "sell"
    action_type = SellAction


class BuyEvaluator(_RewardBackedEvaluator):
    evaluator_id = "buy"
    action_type = BuyAction


class UseEvaluator(_RewardBackedEvaluator):
    evaluator_id = "use"
    action_type = UseAction


class AcceptTaskEvaluator(_RewardBackedEvaluator):
    evaluator_id = "accept_task"
    action_type = AcceptTaskAction


class SubmitAnswerEvaluator(_RewardBackedEvaluator):
    evaluator_id = "submit_answer"
    action_type = SubmitAnswerAction


class TreasureEvaluator(_RewardBackedEvaluator):
    evaluator_id = "summon_treasure"
    action_type = SummonTreasureAction


class BuildEvaluator(_RewardBackedEvaluator):
    evaluator_id = "build"
    action_type = BuildAction
