from __future__ import annotations

from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Mapping


def _empty_mapping() -> Mapping[str, float]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True)
class UtilityBreakdown:
    score: float = 0.0
    survival: float = 0.0
    economy: float = 0.0
    position: float = 0.0
    information: float = 0.0
    future: float = 0.0

    time_cost: float = 0.0
    opportunity_cost: float = 0.0
    risk: float = 0.0

    total: float = 0.0
    # 以下字段仅用于审计/日志，不参与排序之外的任何副作用。
    raw_components: Mapping[str, float] = field(default_factory=_empty_mapping)
    effective_weights: Mapping[str, float] = field(default_factory=_empty_mapping)
    formula: str = ""

    def is_finite(self) -> bool:
        values = [
            self.score,
            self.survival,
            self.economy,
            self.position,
            self.information,
            self.future,
            self.time_cost,
            self.opportunity_cost,
            self.risk,
            self.total,
        ]
        values.extend(self.raw_components.values())
        values.extend(self.effective_weights.values())
        return all(math.isfinite(value) for value in values)
