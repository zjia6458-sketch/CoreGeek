from __future__ import annotations

from fortress_agent.events.store import EventStore
from fortress_agent.memory.projectors.map import MapMemoryProjector
from fortress_agent.memory.projectors.resources import ResourceMemoryProjector
from fortress_agent.memory.snapshot import (
    JsonWorldMemorySnapshotStore,
    WorldMemorySnapshotCodec,
)
from fortress_agent.memory.world import WorldMemory


class WorldMemoryRecovery:
    def __init__(
        self,
        *,
        snapshot_store: JsonWorldMemorySnapshotStore,
        event_store: EventStore,
    ) -> None:
        self._snapshot_store = snapshot_store
        self._event_store = event_store
        self._codec = WorldMemorySnapshotCodec()
        self._projectors = (
            MapMemoryProjector(),
            ResourceMemoryProjector(),
        )

    def recover(self) -> tuple[WorldMemory, int]:
        snapshot = self._snapshot_store.load()

        if snapshot is None:
            memory = WorldMemory()
            snapshot_round = -1
        else:
            memory = self._codec.restore(snapshot)
            snapshot_round = snapshot.round_id

        last_round = snapshot_round

        for event in self._event_store.after_round(snapshot_round):
            for projector in self._projectors:
                if projector.supports(event):
                    projector.apply(memory, event)
            last_round = max(last_round, event.round_id)

        return memory, last_round
