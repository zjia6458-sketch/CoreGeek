from __future__ import annotations

from fortress_agent.config.tuning import DEFAULT_THRESHOLDS
from fortress_agent.domain.policy_state import PolicyPatch, PolicyState
from fortress_agent.learning.experience.stats import RunningStats


class PrepareMarginLearner:
    """保守地微调 prepare 进入时机。

    仅观察 PREPARE 策略的已完成 Outcome，并通过 PolicyPatch 提案。Runtime 是否自动
    promote 由 RuntimeLearningConfig 决定；本类本身不会直接修改生产策略。
    """

    learner_id = "prepare_margin"

    def __init__(
        self,
        *,
        min_samples: int = 5,
        step: float = 1.0,
        minimum: float = 8.0,
        maximum: float = 30.0,
        negative_reward_threshold: float = -0.5,
        positive_reward_threshold: float = 2.0,
    ) -> None:
        self._stats = RunningStats()
        self._min_samples = max(1, int(min_samples))
        self._step = max(0.0, float(step))
        self._minimum = float(minimum)
        self._maximum = float(maximum)
        self._negative = float(negative_reward_threshold)
        self._positive = float(positive_reward_threshold)

    def observe(self, exp, outcome) -> None:
        if outcome is None or outcome.action_legal is False:
            return
        if exp.strategy_id != "prepare":
            return
        self._stats.update(outcome.reward.total)

    def propose(self, current: PolicyState) -> PolicyPatch | None:
        if self._stats.count < self._min_samples:
            return None
        old = float(current.thresholds.get("prepare_margin_rounds", DEFAULT_THRESHOLDS["prepare_margin_rounds"]))

        if self._stats.mean < self._negative:
            new = min(self._maximum, old + self._step)
            reason = "prepare outcomes are persistently negative; start preparation earlier"
        elif self._stats.mean > self._positive:
            new = max(self._minimum, old - self._step)
            reason = "prepare outcomes have strong positive margin; reduce preparation window slightly"
        else:
            return None
        if new == old:
            return None
        return PolicyPatch(
            patch_id=f"prepare-margin:{current.version}:{self._stats.count}",
            parent_version=current.version,
            component="thresholds",
            key="prepare_margin_rounds",
            old_value=old,
            new_value=new,
            reason=reason,
            proposer=self.learner_id,
            confidence=min(0.95, 0.5 + self._stats.count / 100.0),
        )
