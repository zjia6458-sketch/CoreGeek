from fortress_agent.domain.action import GoalApproachAction
from .basic import _RewardBackedEvaluator


class GoalApproachEvaluator(_RewardBackedEvaluator):
    evaluator_id = "goal_approach"
    action_type = GoalApproachAction
