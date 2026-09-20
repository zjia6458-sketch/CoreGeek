from __future__ import annotations

from dataclasses import asdict
from typing import Type

from fortress_agent.events.base import DomainEvent
from fortress_agent.events.world import (
    CellObserved,
    CellVisited,
    ResourceDepleted,
    ResourceDiscovered,
    ResourceReplenished,
    ResourceUpdated,
)

_EVENT_TYPES: dict[str, Type[DomainEvent]] = {
    cls.__name__: cls
    for cls in (
        CellObserved,
        CellVisited,
        ResourceDiscovered,
        ResourceUpdated,
        ResourceDepleted,
        ResourceReplenished,
    )
}


def event_to_dict(event: DomainEvent) -> dict[str, object]:
    return {
        "event_type": type(event).__name__,
        "payload": asdict(event),
    }


def event_from_dict(data: dict[str, object]) -> DomainEvent:
    event_type = str(data["event_type"])
    payload = dict(data["payload"])  # type: ignore[arg-type]

    cls = _EVENT_TYPES.get(event_type)
    if cls is None:
        raise ValueError(f"unknown event type: {event_type}")

    return cls(**payload)
