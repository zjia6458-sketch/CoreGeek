from __future__ import annotations

from dataclasses import dataclass

from .action import Action
from .utility import UtilityBreakdown


@dataclass(frozen=True, slots=True)
class Decision:
    action: Action
    strategy_id: str
    utility: UtilityBreakdown
    matched_rules: tuple[str, ...] = ()
    rejected_reasons: tuple[str, ...] = ()
    policy_version: int = 1
    confidence: float = 1.0
    latency_ms: float = 0.0
