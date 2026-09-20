from __future__ import annotations

from fortress_agent.domain.state import GameState
from fortress_agent.events.base import DomainEvent
from fortress_agent.events.bus import EventBus
from fortress_agent.events.store import EventStore, InMemoryEventStore
from fortress_agent.memory.projectors.map import MapMemoryProjector
from fortress_agent.memory.projectors.resources import ResourceMemoryProjector
from fortress_agent.memory.snapshot import (
    JsonWorldMemorySnapshotStore,
    WorldMemorySnapshotCodec,
)
from fortress_agent.memory.world import WorldMemory, WorldMemoryView

from .interpreter import ObservationInterpreter


class WorldMemoryEngine:
    def __init__(
        self,
        *,
        memory: WorldMemory | None = None,
        interpreter: ObservationInterpreter | None = None,
        event_bus: EventBus | None = None,
        event_store: EventStore | None = None,
        last_observed_round: int = -1,
    ) -> None:
        self._memory = memory or WorldMemory()
        self._interpreter = interpreter or ObservationInterpreter()
        self._event_bus = event_bus or EventBus()
        self._event_store = event_store or InMemoryEventStore()
        self._projectors = (
            MapMemoryProjector(),
            ResourceMemoryProjector(),
        )
        self._snapshot_codec = WorldMemorySnapshotCodec()
        self._last_observed_round = last_observed_round

    def observe(
        self,
        state: GameState,
        *,
        correlation_id: str | None = None,
    ) -> tuple[DomainEvent, ...]:
        # Idempotency guard for HTTP retry / recovered process state.
        if state.round_id <= self._last_observed_round:
            return ()

        events = self._interpreter.interpret(
            state,
            self._memory.view(),
            correlation_id=correlation_id,
        )

        for event in events:
            for projector in self._projectors:
                if projector.supports(event):
                    projector.apply(self._memory, event)

            self._event_store.append(event)
            self._event_bus.publish(event)

        self._last_observed_round = state.round_id
        return events

    def snapshot_to(
        self,
        store: JsonWorldMemorySnapshotStore,
        *,
        round_id: int,
    ) -> None:
        store.save(self._snapshot_codec.dump(self._memory, round_id=round_id))

    def view(self) -> WorldMemoryView:
        return self._memory.view()

    @property
    def memory(self) -> WorldMemory:
        return self._memory

    @property
    def event_store(self) -> EventStore:
        return self._event_store

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    @property
    def last_observed_round(self) -> int:
        return self._last_observed_round

    def close(self) -> None:
        close = getattr(self._event_store, "close", None)
        if close is not None:
            close()
