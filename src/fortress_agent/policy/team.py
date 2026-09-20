from __future__ import annotations

from dataclasses import dataclass

from fortress_agent.domain.decision import Decision
from fortress_agent.domain.auxiliary import AuxiliaryDecision
from fortress_agent.domain.team import TeamDecision
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.worker_priority import worker_action_priority
from fortress_agent.policy.team_constraints import (
    TeamConstraintRegistry,
    build_default_team_constraints,
)


@dataclass(frozen=True, slots=True)
class ConflictResolution:
    """团队级冲突消解结果。"""

    team_decision: TeamDecision
    dropped_decision_ids: tuple[str, ...]


class TeamConflictResolver:
    """按照可注册的 TeamConstraint 处理多角色联合动作冲突。

    具体约束实现位于 ``policy/team_constraints.py``，例如：
    - 同一角色不能同时控制多个武器；
    - 多角色 MOVE 不能争夺同一个目标格；
    - 位置互换等联合移动冲突。
    """

    def __init__(
        self,
        constraints: TeamConstraintRegistry | None = None,
    ) -> None:
        self._constraints = (
            constraints
            or build_default_team_constraints()
        )

    def resolve(
        self,
        decisions: tuple[Decision, ...],
        *,
        ctx: PolicyContext | None = None,
        prompt: str = "",
        execute_cmd: str = "",
        auxiliary_decisions: tuple[AuxiliaryDecision, ...] = (),
    ) -> ConflictResolution:
        result = self._constraints.apply(
            ctx,
            decisions,
        )

        selected = tuple(
            sorted(
                result.decisions,
                key=lambda decision: str(
                    decision.action.actor_id
                ),
            )
        )

        return ConflictResolution(
            team_decision=TeamDecision(
                decisions=selected,
                auxiliary_decisions=auxiliary_decisions,
                prompt=prompt,
                execute_cmd=execute_cmd,
            ),
            dropped_decision_ids=(
                result.dropped_decision_ids
            ),
        )


class TeamPlanner:
    """为每个 actor 选择一个动作，再执行团队级冲突消解。

    ``plan`` 是兼容入口，会自己生成 Candidate/Legal/Rule。
    生产 Runtime 优先使用 ``plan_from_viable``：PolicyGraph 已经完成过一次
    Candidate -> Legal -> Rule，就直接复用 ``frame.viable_actions``，避免第二次
    跑 A* 与候选生成。这是 V0.5.2 的主要超时优化之一。
    """

    def __init__(
        self,
        *,
        strategy_selector,
        candidate_service,
        legal_filter,
        rule_engine,
        ranker,
        conflict_resolver: TeamConflictResolver | None = None,
    ) -> None:
        self._strategy = strategy_selector
        self._candidates = candidate_service
        self._legal = legal_filter
        self._rules = rule_engine
        self._ranker = ranker
        self._conflicts = (
            conflict_resolver
            or TeamConflictResolver()
        )

    def plan(
        self,
        ctx: PolicyContext,
        *,
        prompt: str = "",
        execute_cmd: str = "",
        auxiliary_decisions: tuple[AuxiliaryDecision, ...] = (),
        strategy=None,
    ) -> TeamDecision:
        strategy = (
            strategy
            if strategy is not None
            else self._strategy.select(ctx)
        )

        candidates = self._candidates.generate(
            ctx,
            strategy,
        )
        legal = self._legal.filter(
            ctx,
            candidates,
        )
        viable, matched, rejected = (
            self._rules.apply(
                ctx,
                legal,
            )
        )

        return self.plan_from_viable(
            ctx,
            strategy=strategy,
            viable_actions=viable,
            matched_rules=matched,
            rejected_reasons=rejected,
            prompt=prompt,
            execute_cmd=execute_cmd,
            auxiliary_decisions=auxiliary_decisions,
        )

    def plan_from_viable(
        self,
        ctx: PolicyContext,
        *,
        strategy,
        viable_actions,
        matched_rules: tuple[str, ...] = (),
        rejected_reasons: tuple[str, ...] = (),
        prompt: str = "",
        execute_cmd: str = "",
        auxiliary_decisions: tuple[AuxiliaryDecision, ...] = (),
    ) -> TeamDecision:
        """复用 PolicyGraph 已验证动作，并在团队冲突后尝试 actor 的次优候选。

        旧实现每个 actor 只取第一名；若两人第一步争同一格，TeamConstraint
        会直接丢掉其中一人。本实现保留每个 actor 的有序候选表，在冲突后
        只推进被丢弃 actor 的候选索引，最多重试 12 次。
        """
        by_actor: dict[str, list] = {}
        for action in viable_actions:
            by_actor.setdefault(str(action.actor_id), []).append(action)

        minimum_utility = float(
            strategy.metadata.get("minimum_action_utility", float("-inf"))
        )
        ranked: dict[str, list[Decision]] = {}
        for actor_id, actions in sorted(by_actor.items()):
            if ctx.deadline.remaining() <= 0.45:
                break
            entries = []
            for action, utility in self._ranker.rank_all(ctx, tuple(actions), strategy):
                if utility.total < minimum_utility and worker_action_priority(ctx, action) <= 0:
                    continue
                entries.append(Decision(
                    action=action,
                    strategy_id=strategy.strategy_id,
                    utility=utility,
                    matched_rules=matched_rules,
                    rejected_reasons=rejected_reasons,
                    policy_version=ctx.policy_state.version,
                ))
            if entries:
                ranked[actor_id] = entries

        indices = {actor_id: 0 for actor_id in ranked}
        exhausted: set[str] = set()
        last_resolution = None
        for _ in range(12):
            if ctx.deadline.remaining() <= 0.35:
                break
            selected = tuple(
                ranked[actor_id][indices[actor_id]]
                for actor_id in sorted(ranked)
                if actor_id not in exhausted
                and indices[actor_id] < len(ranked[actor_id])
            )
            last_resolution = self._conflicts.resolve(
                selected,
                ctx=ctx,
                prompt=prompt,
                execute_cmd=execute_cmd,
                auxiliary_decisions=auxiliary_decisions,
            )
            kept_ids = {str(d.action.actor_id) for d in last_resolution.team_decision.decisions}
            dropped_actor_ids = [
                str(d.action.actor_id) for d in selected
                if str(d.action.actor_id) not in kept_ids
            ]
            if not dropped_actor_ids:
                return last_resolution.team_decision
            progressed = False
            for actor_id in dropped_actor_ids:
                indices[actor_id] += 1
                progressed = True
                if indices[actor_id] >= len(ranked[actor_id]):
                    exhausted.add(actor_id)
            if not progressed:
                break

        if last_resolution is not None:
            return last_resolution.team_decision
        return TeamDecision(decisions=(), auxiliary_decisions=auxiliary_decisions, prompt=prompt, execute_cmd=execute_cmd)
