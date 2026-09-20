from __future__ import annotations

from fortress_agent.events.base import DomainEvent
from fortress_agent.events.world import CellObserved, CellVisited
from fortress_agent.memory.world import WorldMemory


class MapMemoryProjector:
    def supports(self, event: DomainEvent) -> bool:
        return isinstance(event, (CellObserved, CellVisited))

    def apply(self, memory: WorldMemory, event: DomainEvent) -> None:
        if isinstance(event, CellObserved):
            memory.map.observe(
                x=event.x,
                y=event.y,
                round_id=event.round_id,
                terrain=event.terrain,
            )
        elif isinstance(event, CellVisited):
            memory.map.visit(
                x=event.x,
                y=event.y,
                round_id=event.round_id,
            )
