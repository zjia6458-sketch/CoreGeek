from __future__ import annotations

from fortress_agent.learning.experience.record import (
    ExperienceRecord,
)
from fortress_agent.learning.experience.store import (
    ExperienceStore,
)


class RollbackPolicy:
    def __init__(
        self,
        *,
        minimum_samples: int = 5,
        severe_reward_threshold: float = -10.0,
        mean_reward_threshold: float = -2.0,
    ) -> None:
        self.minimum_samples = minimum_samples
        self.severe_reward_threshold = severe_reward_threshold
        self.mean_reward_threshold = mean_reward_threshold

    def should_rollback(
        self,
        *,
        current_version: int,
        experiences: ExperienceStore,
    ) -> bool:
        rewards = []

        for exp in experiences.recent(
            self.minimum_samples * 4
        ):
            if exp.policy_version != current_version:
                continue

            outcome = experiences.outcome_for(
                exp.decision_id
            )
            if outcome is None:
                continue

            value = outcome.reward.total

            if value <= self.severe_reward_threshold:
                return True

            rewards.append(value)

        if len(rewards) < self.minimum_samples:
            return False

        return (
            sum(rewards) / len(rewards)
            < self.mean_reward_threshold
        )
