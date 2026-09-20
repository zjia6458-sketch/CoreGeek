from __future__ import annotations

from fortress_agent.events.base import DomainEvent
from fortress_agent.events.world import (
    ResourceDepleted,
    ResourceDiscovered,
    ResourceReplenished,
    ResourceUpdated,
)
from fortress_agent.memory.world import WorldMemory


class ResourceMemoryProjector:
    def supports(self, event: DomainEvent) -> bool:
        return isinstance(
            event,
            (
                ResourceDiscovered,
                ResourceUpdated,
                ResourceDepleted,
                ResourceReplenished,
            ),
        )

    def apply(self, memory: WorldMemory, event: DomainEvent) -> None:
        if isinstance(event, ResourceDiscovered):
            memory.resources.discover(
                resource_id=event.resource_id,
                resource_type=event.resource_type,
                x=event.x,
                y=event.y,
                amount=event.amount,
                round_id=event.round_id,
            )
        elif isinstance(event, ResourceUpdated):
            memory.resources.update(
                resource_id=event.resource_id,
                amount=event.amount,
                round_id=event.round_id,
            )
        elif isinstance(event, ResourceDepleted):
            memory.resources.deplete(
                resource_id=event.resource_id,
                round_id=event.round_id,
            )
        elif isinstance(event, ResourceReplenished):
            memory.resources.replenish(
                resource_id=event.resource_id,
                resource_type=event.resource_type,
                x=event.x,
                y=event.y,
                amount=event.amount,
                round_id=event.round_id,
            )
