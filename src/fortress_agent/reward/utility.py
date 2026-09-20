from __future__ import annotations

from types import MappingProxyType

from fortress_agent.config.tuning import DEFAULT_UTILITY_WEIGHT_MULTIPLIERS
from fortress_agent.domain.reward import RewardBreakdown
from fortress_agent.domain.utility import UtilityBreakdown
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.strategy import StrategyProfile


BASE_WEIGHTS = {
    "score": 1.0,
    "survival": 1.0,
    "economy": 1.0,
    "information": 1.0,
    "position": 1.0,
    "task": 1.0,
    "time_cost": 1.0,
    "opportunity_cost": 1.0,
    "risk": 1.0,
}


class UtilityComposer:
    """把 Reward 组合为可审计的 Strategy-sensitive Utility。

    有效权重 = StrategyProfile 基准权重 × PolicyState 运行时倍率。
    这样 Strategy 仍能表达 defense/economy/task 的结构差异，而在线学习只需把
    ``economy multiplier`` 从 1.00 小幅改成 1.05，不会覆盖整个 StrategyProfile。
    """

    def compose(
        self,
        ctx: PolicyContext,
        strategy: StrategyProfile,
        reward: RewardBreakdown,
    ) -> UtilityBreakdown:
        strategy_weights = dict(BASE_WEIGHTS)
        strategy_weights.update(strategy.utility_weight_overrides)
        multipliers = dict(DEFAULT_UTILITY_WEIGHT_MULTIPLIERS)
        multipliers.update(ctx.policy_state.utility_weights)

        effective = {
            key: float(strategy_weights.get(key, 1.0)) * float(multipliers.get(key, 1.0))
            for key in BASE_WEIGHTS
        }

        raw = {
            "score": float(reward.score),
            "survival": float(reward.survival),
            "economy": float(reward.economy),
            "information": float(reward.information),
            "position": float(reward.position),
            "task": float(reward.task),
            "time_cost": float(reward.action_cost),
            "opportunity_cost": 0.0,
            "risk": float(reward.risk),
        }

        score = raw["score"] * effective["score"]
        survival = raw["survival"] * effective["survival"]
        economy = raw["economy"] * effective["economy"]
        information = raw["information"] * effective["information"]
        position = raw["position"] * effective["position"]
        task = raw["task"] * effective["task"]
        time_cost = raw["time_cost"] * effective["time_cost"]
        opportunity_cost = raw["opportunity_cost"] * effective["opportunity_cost"]
        risk = (
            raw["risk"]
            * effective["risk"]
            * float(ctx.policy_state.risk_weight)
            * float(strategy.risk_multiplier)
        )

        total = (
            score + survival + economy + information + position + task
            - time_cost - opportunity_cost - risk
        )
        formula = (
            "U=score*w_s+survival*w_surv+economy*w_econ+information*w_info+"
            "position*w_pos+task*w_task-time*w_time-opportunity*w_opp-"
            "risk*w_risk*riskWeight*strategyRisk"
        )

        return UtilityBreakdown(
            score=score,
            survival=survival,
            economy=economy,
            information=information,
            position=position,
            future=task,
            time_cost=time_cost,
            opportunity_cost=opportunity_cost,
            risk=risk,
            total=total,
            raw_components=MappingProxyType(raw),
            effective_weights=MappingProxyType(effective),
            formula=formula,
        )
