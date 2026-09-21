from __future__ import annotations

from dataclasses import dataclass

from fortress_agent.domain.state import GameState, Position, ResourceNodeState
from fortress_agent.game_rules.catalog import (
    RESOURCE_TYPES as _RESOURCE_TYPES,
    TASK_ZONE_TYPES as _TASK_ZONE_TYPES,
    NEUTRAL_BLOCKER_TYPES,
)
from fortress_agent.game_rules.geometry import is_adjacent8, neighbors8
from fortress_agent.world.occupancy import BuildingFootprintResolver

RESOURCE_ZONE_TYPES = _RESOURCE_TYPES
TASK_ZONE_TYPES = _TASK_ZONE_TYPES


def _norm(value: str) -> str:
    return str(value).strip().casefold()


_NEUTRAL_BLOCKERS_NORM = frozenset(_norm(x) for x in NEUTRAL_BLOCKER_TYPES)
_TASK_TYPES_NORM = frozenset(_norm(x) for x in TASK_ZONE_TYPES)
_RESOURCE_TYPES_NORM = frozenset(_norm(x) for x in RESOURCE_ZONE_TYPES)


@dataclass(frozen=True, slots=True)
class TraversabilityMap:
    """Authoritative movement feasibility for the current round.

    Static blockers: buildings and neutral blockers (vendor, weapon shop, all
    four task points, active mines). Dynamic blockers: visible characters and
    robots. Learned terrain rules are semantic by terrain type.

    Own-role occupancy is intentionally conservative: moving into a teammate's
    current cell is filtered here. Joint move conflict handling adds another
    safety layer for same-target and swap conflicts.
    """

    width: int
    height: int
    blocked: frozenset[tuple[int, int]]
    resource_cells: frozenset[tuple[int, int]]
    task_cells: frozenset[tuple[int, int]]
    neutral_cells: frozenset[tuple[int, int]]
    building_cells: frozenset[tuple[int, int]]
    character_cells: frozenset[tuple[int, int]]
    robot_cells: frozenset[tuple[int, int]]
    learned_terrain_types: frozenset[str]
    learned_terrain_cells: tuple[tuple[int, int, str], ...]
    retry_blocked_cells: frozenset[tuple[int, int]] = frozenset()

    @classmethod
    def from_state(cls, state: GameState) -> "TraversabilityMap":
        resource_cells = {
            (resource.position.x, resource.position.y)
            for resource in state.resources
            if resource.active
        }

        task_cells: set[tuple[int, int]] = set()
        neutral_cells: set[tuple[int, int]] = set()
        for zone in state.neutral_zones:
            normalized = _norm(zone.zone_type)
            pos = (zone.position.x, zone.position.y)
            if normalized in _NEUTRAL_BLOCKERS_NORM:
                neutral_cells.add(pos)
            if normalized in _TASK_TYPES_NORM:
                # Task content may expire, but the four physical TaskPoint map
                # elements remain movement blockers by the official rules.
                task_cells.add(pos)
            if normalized in _RESOURCE_TYPES_NORM:
                resource_cells.add(pos)

        building_cells: set[tuple[int, int]] = set()
        for building in state.buildings:
            for pos in BuildingFootprintResolver.cells(
                building,
                map_width=state.map_width,
                map_height=state.map_height,
            ):
                building_cells.add((pos.x, pos.y))

        character_cells = {
            (actor.position.x, actor.position.y)
            for actor in (*state.characters, *state.opponent_characters)
            if actor.hp > 0
        }
        robot_cells = {
            (enemy.position.x, enemy.position.y)
            for enemy in state.enemies
            if enemy.hp > 0
        }

        blocked = (
            resource_cells
            | task_cells
            | neutral_cells
            | building_cells
            | character_cells
            | robot_cells
        )
        return cls(
            width=state.map_width,
            height=state.map_height,
            blocked=frozenset(blocked),
            resource_cells=frozenset(resource_cells),
            task_cells=frozenset(task_cells),
            neutral_cells=frozenset(neutral_cells),
            building_cells=frozenset(building_cells),
            character_cells=frozenset(character_cells),
            robot_cells=frozenset(robot_cells),
            learned_terrain_types=frozenset(),
            learned_terrain_cells=(),
        )

    @classmethod
    def from_state_and_memory(
        cls,
        state: GameState,
        memory,
        feedback_memory=None,
    ) -> "TraversabilityMap":
        base = cls.from_state(state)
        remembered_resources = {
            (resource.x, resource.y)
            for resource in memory.available_resources()
        }

        learned_types: set[str] = set()
        retry_cells: frozenset[tuple[int, int]] = frozenset()
        if feedback_memory is not None:
            learned_types = {
                _norm(item)
                for item in feedback_memory.impassable_terrain_types()
            }
            retry_cells = feedback_memory.move_retry_blocked_cells(state.round_id)

        learned_cells_with_type = tuple(
            sorted(
                (
                    zone.position.x,
                    zone.position.y,
                    zone.zone_type,
                )
                for zone in state.neutral_zones
                if _norm(zone.zone_type) in learned_types
            )
        )
        learned_cells = {(x, y) for x, y, _ in learned_cells_with_type}

        resource_cells = set(base.resource_cells) | remembered_resources
        blocked = (
            resource_cells
            | set(base.task_cells)
            | set(base.neutral_cells)
            | set(base.building_cells)
            | set(base.character_cells)
            | set(base.robot_cells)
            | learned_cells
            | retry_cells
        )

        return cls(
            width=base.width,
            height=base.height,
            blocked=frozenset(blocked),
            resource_cells=frozenset(resource_cells),
            task_cells=base.task_cells,
            neutral_cells=base.neutral_cells,
            building_cells=base.building_cells,
            character_cells=base.character_cells,
            robot_cells=base.robot_cells,
            learned_terrain_types=frozenset(learned_types),
            learned_terrain_cells=learned_cells_with_type,
            retry_blocked_cells=retry_cells,
        )

    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_walkable(self, x: int, y: int) -> bool:
        return self.inside(x, y) and (x, y) not in self.blocked

    def is_resource_cell(self, x: int, y: int) -> bool:
        return (x, y) in self.resource_cells

    def is_task_cell(self, x: int, y: int) -> bool:
        return (x, y) in self.task_cells

    def learned_terrain_at(self, x: int, y: int) -> str | None:
        for lx, ly, terrain_type in self.learned_terrain_cells:
            if lx == x and ly == y:
                return terrain_type
        return None

    def block_reason(self, x: int, y: int) -> str | None:
        if not self.inside(x, y):
            return "out_of_map"
        if (x, y) in self.retry_blocked_cells:
            return "temporary_move_retry_ban"
        learned = self.learned_terrain_at(x, y)
        if learned is not None:
            return f"learned_impassable_terrain:{learned}"
        if (x, y) in self.resource_cells:
            return "resource_cell"
        if (x, y) in self.task_cells:
            return "task_point_cell"
        if (x, y) in self.building_cells:
            return "building_cell"
        if (x, y) in self.robot_cells:
            return "robot_cell"
        if (x, y) in self.character_cells:
            return "character_cell"
        if (x, y) in self.neutral_cells:
            return "neutral_unit_cell"
        return None

    def walkable_neighbors(self, x: int, y: int) -> tuple[Position, ...]:
        return tuple(
            Position(nx, ny)
            for nx, ny in neighbors8(x, y)
            if self.is_walkable(nx, ny)
        )

    def interaction_access_cells(self, position: Position) -> tuple[Position, ...]:
        return self.walkable_neighbors(position.x, position.y)

    def resource_access_cells(self, resource: ResourceNodeState | object) -> tuple[Position, ...]:
        x = getattr(resource, "x", None)
        y = getattr(resource, "y", None)
        if x is None or y is None:
            position = getattr(resource, "position")
            x, y = position.x, position.y
        return self.walkable_neighbors(int(x), int(y))

    @staticmethod
    def is_adjacent(a: Position, b: Position) -> bool:
        return is_adjacent8(a, b)
