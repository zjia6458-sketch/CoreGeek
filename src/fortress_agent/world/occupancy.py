from __future__ import annotations

from dataclasses import dataclass

from fortress_agent.domain.state import (
    BuildingState,
    GameState,
    Position,
)


class BuildingFootprintResolver:
    @staticmethod
    def cells(
        building: BuildingState,
        *,
        map_width: int,
        map_height: int,
    ) -> tuple[Position, ...]:
        x = building.position.x
        y = building.position.y

        if building.footprint_anchor == "top_left":
            raw = tuple(
                Position(x + dx, y - dy)
                for dy in range(building.footprint_height)
                for dx in range(building.footprint_width)
            )
        else:
            raw = (building.position,)

        return tuple(
            pos
            for pos in raw
            if (
                0 <= pos.x < map_width
                and 0 <= pos.y < map_height
            )
        )


@dataclass(frozen=True, slots=True)
class OccupancyMap:
    blocked: frozenset[tuple[int, int]]

    def is_blocked(self, x: int, y: int) -> bool:
        return (x, y) in self.blocked

    @classmethod
    def from_state(
        cls,
        state: GameState,
    ) -> "OccupancyMap":
        cells: set[tuple[int, int]] = set()

        for building in state.buildings:
            for pos in BuildingFootprintResolver.cells(
                building,
                map_width=state.map_width,
                map_height=state.map_height,
            ):
                cells.add((pos.x, pos.y))

        return cls(frozenset(cells))
