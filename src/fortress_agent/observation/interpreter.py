from __future__ import annotations

from fortress_agent.game_rules.constants import SHARED_VISION_RANGE

from fortress_agent.domain.state import GameState
from fortress_agent.events.base import DomainEvent
from fortress_agent.events.world import (
    CellObserved,
    CellVisited,
    ResourceDepleted,
    ResourceDiscovered,
    ResourceReplenished,
    ResourceUpdated,
)
from fortress_agent.memory.resources import ResourceStatus
from fortress_agent.memory.world import WorldMemoryView


class ObservationInterpreter:
    """Derive factual world events from the current GameState and previous memory."""

    def interpret(
        self,
        state: GameState,
        memory: WorldMemoryView,
        *,
        correlation_id: str | None = None,
    ) -> tuple[DomainEvent, ...]:
        events: list[DomainEvent] = []
        sequence = 0

        def next_id(kind: str) -> str:
            nonlocal sequence
            sequence += 1
            return f"r{state.round_id}:{sequence}:{kind}"

        correlation_id = correlation_id or f"round:{state.round_id}"

        # 1. Explicit visibility supplied by the server.
        explicitly_observed: set[tuple[int, int]] = set()

        for cell in state.observed_cells:
            explicitly_observed.add((cell.x, cell.y))
            events.append(
                CellObserved(
                    event_id=next_id("cell_observed"),
                    round_id=state.round_id,
                    correlation_id=correlation_id,
                    x=cell.x,
                    y=cell.y,
                    terrain=cell.terrain,
                )
            )

        # 2. A character's own tile is always known and visited.
        # It is also safe evidence that the exact tile is currently observable.
        currently_observed = set(explicitly_observed)

        for actor in state.characters:
            x, y = actor.position.x, actor.position.y
            currently_observed.add((x, y))

            if (x, y) not in explicitly_observed:
                events.append(
                    CellObserved(
                        event_id=next_id("cell_observed"),
                        round_id=state.round_id,
                        correlation_id=correlation_id,
                        x=x,
                        y=y,
                        terrain=None,
                    )
                )

            events.append(
                CellVisited(
                    event_id=next_id("cell_visited"),
                    round_id=state.round_id,
                    correlation_id=correlation_id,
                    actor_id=actor.actor_id,
                    x=x,
                    y=y,
                )
            )


        # 2a. Official shared vision: every own character/building contributes
        # Chebyshev radius 4. The protocol does not enumerate observed cells,
        # so derive visibility deterministically from own units.
        visibility_sources = [actor.position for actor in state.characters]
        for building in state.buildings:
            if building.owner == "self":
                visibility_sources.append(building.position)

        for source in visibility_sources:
            for x in range(max(0, source.x - SHARED_VISION_RANGE), min(state.map_width, source.x + SHARED_VISION_RANGE + 1)):
                for y in range(max(0, source.y - SHARED_VISION_RANGE), min(state.map_height, source.y + SHARED_VISION_RANGE + 1)):
                    if max(abs(x - source.x), abs(y - source.y)) > 4:
                        continue
                    currently_observed.add((x, y))
                    known_cell = memory.cell(x, y)
                    if not known_cell.discovered or known_cell.last_seen_round != state.round_id:
                        events.append(
                            CellObserved(
                                event_id=next_id("cell_observed"),
                                round_id=state.round_id,
                                correlation_id=correlation_id,
                                x=x,
                                y=y,
                                terrain=None,
                            )
                        )

        # Neutral zones are supplied as authoritative map facts. Mark their
        # exact cells known even when outside current visual radius.
        for zone in state.neutral_zones:
            currently_observed.add((zone.position.x, zone.position.y))
            events.append(
                CellObserved(
                    event_id=next_id("cell_observed"),
                    round_id=state.round_id,
                    correlation_id=correlation_id,
                    x=zone.position.x,
                    y=zone.position.y,
                    terrain=zone.zone_type,
                )
            )

        # 3. Resources currently present in the response.
        current_resource_ids = set()

        for resource in state.resources:
            current_resource_ids.add(resource.resource_id)
            known = memory.resource(resource.resource_id)

            # Explicit amount 0 / active false is direct depletion evidence.
            if not resource.active or resource.amount == 0:
                if known is None:
                    # Preserve knowledge that the resource existed before marking depleted.
                    events.append(
                        ResourceDiscovered(
                            event_id=next_id("resource_discovered"),
                            round_id=state.round_id,
                            correlation_id=correlation_id,
                            resource_id=resource.resource_id,
                            resource_type=resource.resource_type,
                            x=resource.position.x,
                            y=resource.position.y,
                            amount=resource.amount,
                        )
                    )
                events.append(
                    ResourceDepleted(
                        event_id=next_id("resource_depleted"),
                        round_id=state.round_id,
                        correlation_id=correlation_id,
                        resource_id=resource.resource_id,
                        x=resource.position.x,
                        y=resource.position.y,
                    )
                )
                continue

            if known is None:
                events.append(
                    ResourceDiscovered(
                        event_id=next_id("resource_discovered"),
                        round_id=state.round_id,
                        correlation_id=correlation_id,
                        resource_id=resource.resource_id,
                        resource_type=resource.resource_type,
                        x=resource.position.x,
                        y=resource.position.y,
                        amount=resource.amount,
                    )
                )
            elif known.status is ResourceStatus.DEPLETED:
                events.append(
                    ResourceReplenished(
                        event_id=next_id("resource_replenished"),
                        round_id=state.round_id,
                        correlation_id=correlation_id,
                        resource_id=resource.resource_id,
                        resource_type=resource.resource_type,
                        x=resource.position.x,
                        y=resource.position.y,
                        amount=resource.amount,
                    )
                )
            elif known.last_known_amount != resource.amount:
                events.append(
                    ResourceUpdated(
                        event_id=next_id("resource_updated"),
                        round_id=state.round_id,
                        correlation_id=correlation_id,
                        resource_id=resource.resource_id,
                        amount=resource.amount,
                    )
                )

        # 4. Missing resource != depleted resource.
        # Only mark a previously available resource depleted when its exact cell
        # is known to be observed *this round* and the resource is absent.
        for known in memory.resources.all():
            if known.status is not ResourceStatus.AVAILABLE:
                continue
            if known.resource_id in current_resource_ids:
                continue
            if (
                not state.map_snapshot_complete
                and (known.x, known.y) not in currently_observed
            ):
                continue

            events.append(
                ResourceDepleted(
                    event_id=next_id("resource_depleted"),
                    round_id=state.round_id,
                    correlation_id=correlation_id,
                    resource_id=known.resource_id,
                    x=known.x,
                    y=known.y,
                )
            )

        return tuple(events)
