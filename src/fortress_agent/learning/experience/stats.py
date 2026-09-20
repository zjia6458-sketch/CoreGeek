from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(slots=True)
class RunningStats:
    count: int = 0
    mean: float = 0.0
    m2: float = 0.0
    ema: float = 0.0
    ema_alpha: float = 0.2

    def update(self, value: float) -> None:
        self.count += 1

        delta = value - self.mean
        self.mean += delta / self.count

        delta2 = value - self.mean
        self.m2 += delta * delta2

        if self.count == 1:
            self.ema = value
        else:
            self.ema = (
                self.ema_alpha * value
                + (1.0 - self.ema_alpha) * self.ema
            )

    @property
    def variance(self) -> float:
        if self.count < 2:
            return 0.0
        return self.m2 / (self.count - 1)

    @property
    def std(self) -> float:
        return math.sqrt(max(0.0, self.variance))


@dataclass(frozen=True, slots=True)
class ContextKey:
    phase: str
    strategy_id: str
    action_type: str
