from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class StrategyObjective:
    objective_id: str
    priority: float
    description: str = ""


@dataclass(frozen=True, slots=True)
class StrategyProfile:
    strategy_id: str
    candidate_tags: frozenset[str]
    utility_weight_overrides: Mapping[str, float] = field(
        default_factory=lambda: MappingProxyType({})
    )
    risk_multiplier: float = 1.0

    # Rich strategy information. Existing Candidate/Evaluator plugins may
    # ignore these fields; complex plugins can consume them through metadata.
    objectives: tuple[StrategyObjective, ...] = ()
    metadata: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
