from __future__ import annotations

from fortress_agent.domain.policy_state import PolicyPatch, PolicyState
from fortress_agent.learning.experience.stats import RunningStats


class UtilityWeightLearner:
    """从 Gather 的 realized-vs-predicted 误差微调 economy multiplier。"""

    learner_id = "utility_weight_economy"

    def __init__(
        self,
        *,
        min_samples: int = 5,
        learning_rate: float = 0.05,
        minimum: float = 0.75,
        maximum: float = 1.25,
        error_deadband: float = 0.5,
    ) -> None:
        self._errors = RunningStats()
        self._min_samples = max(1, int(min_samples))
        self._learning_rate = max(0.0, float(learning_rate))
        self._minimum = float(minimum)
        self._maximum = float(maximum)
        self._deadband = max(0.0, float(error_deadband))

    def observe(self, exp, outcome) -> None:
        if outcome is None or outcome.action_legal is False:
            return
        if exp.action.action_type != "gather":
            return
        self._errors.update(outcome.reward.total - exp.predicted_utility.total)

    def propose(self, current: PolicyState) -> PolicyPatch | None:
        if self._errors.count < self._min_samples:
            return None
        mean_error = self._errors.mean
        if abs(mean_error) < self._deadband:
            return None
        old = float(current.utility_weights.get("economy", 1.0))
        direction = 1.0 if mean_error > 0 else -1.0
        new = min(self._maximum, max(self._minimum, old + direction * self._learning_rate))
        if new == old:
            return None
        return PolicyPatch(
            patch_id=f"economy-weight:{current.version}:{self._errors.count}",
            parent_version=current.version,
            component="utility_weights",
            key="economy",
            old_value=old,
            new_value=new,
            reason="calibrate economy utility multiplier from realized-vs-predicted gather reward error",
            proposer=self.learner_id,
            confidence=min(0.9, 0.5 + self._errors.count / 100.0),
        )
