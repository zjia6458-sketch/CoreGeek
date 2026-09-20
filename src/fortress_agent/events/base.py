from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    event_id: str
    round_id: int
    correlation_id: str | None = None
    causation_id: str | None = None
