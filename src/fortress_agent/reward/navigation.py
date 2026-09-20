from __future__ import annotations

from fortress_agent.domain.action import GoalApproachAction
from fortress_agent.domain.reward import RewardBreakdown
from fortress_agent.game_rules.geometry import chebyshev_distance
from fortress_agent.game_rules.economy import wall_construction_due, wall_return_urgent
from fortress_agent.policy.context import PolicyContext
from fortress_agent.world.threat import ThreatMapBuilder

from .base import ExpectedRewardModel


class GoalApproachRewardModel(ExpectedRewardModel):
    model_id = "goal_approach"

    def __init__(self, threat_builder: ThreatMapBuilder | None = None) -> None:
        self._threat = threat_builder or ThreatMapBuilder()

    def supports(self, action) -> bool:
        return type(action) is GoalApproachAction

    def estimate(self, ctx: PolicyContext, action: GoalApproachAction) -> RewardBreakdown:
        remaining = chebyshev_distance((action.x, action.y), (action.goal_x, action.goal_y))
        risk_map, _ = self._threat.build(ctx.state)
        risk = risk_map.value(action.x, action.y) * 0.02
        backtrack = (
            ctx.movement_history.backtrack_penalty(action.actor_id, action.x, action.y)
            if ctx.movement_history is not None else 0.0
        )
        action_cost = 0.10 + backtrack

        if action.goal_kind == "task":
            task = next((t for t in ctx.state.tasks if str(t.task_id) == action.goal_id), None)
            reward = float(task.reward or 20.0) if task is not None else 20.0
            task_value = min(12.0, reward / max(2.0, remaining + 1.0))
            total = task_value - action_cost - risk
            return RewardBreakdown(task=task_value, position=1.0, risk=risk, action_cost=action_cost, total=total + 1.0)

        if action.goal_kind == "vendor":
            actor = next(a for a in ctx.state.characters if a.actor_id == action.actor_id)
            inventory_value = sum(
                item.amount * float(ctx.state.market_prices.get(item.item_type, 0.0))
                for item in actor.inventory
            )
            economy = min(8.0, inventory_value / max(2.0, remaining + 1.0))
            total = economy + 0.5 - action_cost - risk
            return RewardBreakdown(economy=economy, position=0.5, risk=risk, action_cost=action_cost, total=total)

        if action.goal_kind == "weapon_shop":
            survival = 2.0
            total = survival + 0.5 - action_cost - risk
            return RewardBreakdown(survival=survival, position=0.5, risk=risk, action_cost=action_cost, total=total)

        if action.goal_kind == "base":
            urgency = 3.5 if ctx.state.turns_until_phase_change is not None and ctx.state.turns_until_phase_change <= 20 else 1.5
            total = urgency + 1.0 - action_cost - risk
            return RewardBreakdown(survival=urgency, position=1.0, risk=risk, action_cost=action_cost, total=total)

        if action.goal_kind == "defense_post":
            # 夜间走到武器控制位是 attack 的前置条件，必须明显压过随机 move。
            survival = 5.0
            total = survival + 2.0 - action_cost - risk
            return RewardBreakdown(survival=survival, position=2.0, risk=risk, action_cost=action_cost, total=total)


        if action.goal_kind == "upgrade_target":
            survival = 7.0
            position = 2.5 / max(1.0, float(remaining))
            total = survival + position - action_cost - risk
            return RewardBreakdown(survival=survival, position=position, risk=risk, action_cost=action_cost, total=total)

        if action.goal_kind == "wall_repair":
            survival = 8.0
            position = 2.5 / max(1.0, float(remaining))
            total = survival + position - action_cost - risk
            return RewardBreakdown(survival=survival, position=position, risk=risk, action_cost=action_cost, total=total)

        if action.goal_kind == "wall_rebuild":
            survival = 9.0
            position = 3.0 / max(1.0, float(remaining))
            total = survival + position - action_cost - risk
            return RewardBreakdown(survival=survival, position=position, risk=risk, action_cost=action_cost, total=total)

        if action.goal_kind == "rocket_controller":
            survival = 7.0
            position = 3.0 / max(1.0, float(remaining))
            total = survival + position - action_cost - risk
            return RewardBreakdown(survival=survival, position=position, risk=risk, action_cost=action_cost, total=total)

        if action.goal_kind == "weapon_build":
            survival = 6.0
            position = 2.0 / max(1.0, float(remaining))
            total = survival + position - action_cost - risk
            return RewardBreakdown(survival=survival, position=position, risk=risk, action_cost=action_cost, total=total)

        if action.goal_kind == "wall_build":
            # 携带 stone 返回施工圈是“采矿 -> 建墙”闭环的必要中间步骤。
            survival = 5.0 if wall_construction_due(ctx.state, ctx.policy_state) else 3.5
            if wall_return_urgent(ctx.state, ctx.policy_state):
                survival += 4.0
            position = 2.0 / max(1.0, float(remaining))
            total = survival + position - action_cost - risk
            return RewardBreakdown(survival=survival, position=position, risk=risk, action_cost=action_cost, total=total)

        return RewardBreakdown(position=0.25, action_cost=action_cost, risk=risk, total=0.25-action_cost-risk)
