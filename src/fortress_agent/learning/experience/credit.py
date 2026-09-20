from __future__ import annotations

from dataclasses import replace

from fortress_agent.domain.reward import RewardBreakdown
from fortress_agent.learning.experience.record import ExperienceRecord


class TeamCreditAssigner:
    """First replaceable team-reward credit model.

    The scoreboard/reward is team-level. Until causal estimators are available,
    divide it equally among commands that were not explicitly reported illegal.
    Illegal actions receive zero reward and are marked action_legal=False so
    Learners can ignore them.

    This approximation is intentionally isolated behind one component.
    """

    def assign(
        self,
        *,
        experiences: tuple[ExperienceRecord, ...],
        reward: RewardBreakdown,
        legality: dict[str, bool],
    ) -> tuple[tuple[ExperienceRecord, RewardBreakdown, bool | None], ...]:
        if not experiences:
            return ()

        eligible = [
            exp
            for exp in experiences
            if legality.get(
                str(exp.action.actor_id)
            ) is not False
        ]

        weight = (
            1.0 / len(eligible)
            if eligible
            else 0.0
        )

        rows = []

        for exp in experiences:
            legal = legality.get(
                str(exp.action.actor_id)
            )

            scaled = (
                self._scale(reward, weight)
                if legal is not False
                else self._scale(reward, 0.0)
            )

            rows.append((exp, scaled, legal))

        return tuple(rows)

    @staticmethod
    def _scale(
        reward: RewardBreakdown,
        weight: float,
    ) -> RewardBreakdown:
        return RewardBreakdown(
            score=reward.score * weight,
            survival=reward.survival * weight,
            economy=reward.economy * weight,
            information=reward.information * weight,
            position=reward.position * weight,
            task=reward.task * weight,
            action_cost=reward.action_cost * weight,
            risk=reward.risk * weight,
            total=reward.total * weight,
        )
