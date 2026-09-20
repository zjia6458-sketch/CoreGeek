from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class RewardBreakdown:
    """Raw reward signal.

    Reward describes what an action is expected/observed to gain or lose.
    It intentionally does NOT contain strategy-specific weights.
    """

    score: float = 0.0
    survival: float = 0.0
    economy: float = 0.0
    information: float = 0.0
    position: float = 0.0
    task: float = 0.0

    action_cost: float = 0.0
    risk: float = 0.0

    total: float = 0.0

    def is_finite(self) -> bool:
        return all(
            math.isfinite(value)
            for value in (
                self.score,
                self.survival,
                self.economy,
                self.information,
                self.position,
                self.task,
                self.action_cost,
                self.risk,
                self.total,
            )
        )
