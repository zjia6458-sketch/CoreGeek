from __future__ import annotations

from dataclasses import asdict

from fortress_agent.events.base import DomainEvent
from .trace import TraceEvent, TraceSink


class DomainEventTraceAdapter:
    def __init__(self, sink: TraceSink) -> None:
        self._sink = sink

    def __call__(self, event: DomainEvent) -> None:
        self._sink.emit(
            TraceEvent(
                kind="domain_event",
                round_id=event.round_id,
                message=type(event).__name__,
                data={
                    "event_type": type(event).__name__,
                    "payload": asdict(event),
                },
                correlation_id=event.correlation_id,
                event_id=(
                    f"trace:{event.event_id}"
                    if event.event_id
                    else None
                ),
            )
        )
