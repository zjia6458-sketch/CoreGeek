from __future__ import annotations

from fortress_agent.domain.action import GatherAction

from .base import Rule, RuleResult


class GatherOnlyDuringDayRule(Rule):
    rule_id = "gather_only_during_day"
    priority = 10

    def evaluate(self, ctx, action):
        if not isinstance(action, GatherAction):
            return RuleResult(allowed=True)

        # 官方/当前比赛规则允许 Worker 夜间采矿；夜间是否“值得/安全”由
        # NightResourceApproach / night_gather_is_safe 在 Candidate 层做硬安全门控。
        if ctx.state.phase.lower() not in {"day", "night"}:
            return RuleResult(
                allowed=False,
                matched=True,
                reason="unknown phase for gather",
            )

        return RuleResult(allowed=True, matched=True)


class GatherWorkerOnlyRule(Rule):
    rule_id = "gather_worker_only"
    priority = 20

    def evaluate(self, ctx, action):
        if not isinstance(action, GatherAction):
            return RuleResult(allowed=True)

        actor = next(
            (
                actor
                for actor in ctx.state.characters
                if actor.actor_id == action.actor_id
            ),
            None,
        )

        if actor is None or actor.role.lower() != "worker":
            return RuleResult(
                allowed=False,
                matched=True,
                reason="only worker can gather",
            )

        return RuleResult(allowed=True, matched=True)
