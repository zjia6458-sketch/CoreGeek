from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Protocol

from fortress_agent.domain.state import BuildingState, GameState, Position
from fortress_agent.game_rules.catalog import WEAPON_TYPES
from fortress_agent.game_rules.geometry import chebyshev_distance
from fortress_agent.world.occupancy import BuildingFootprintResolver
from fortress_agent.world.traversability import TraversabilityMap

Cell = tuple[int, int]


class BuildAreaType(str, Enum):
    NONE = "none"
    STATION = "station"
    WEAPON = "weapon"
    WALL = "wall"


def _cell(value: Position | Cell) -> Cell:
    if isinstance(value, Position):
        return (value.x, value.y)
    return (int(value[0]), int(value[1]))


def _self_station(state: GameState) -> BuildingState | None:
    return next(
        (
            building
            for building in state.buildings
            if building.owner == "self" and building.building_type == "station"
        ),
        None,
    )


def station_footprint_cells(state: GameState) -> frozenset[Cell]:
    """Return the authoritative occupied cells of our 2x2 station footprint."""
    station = _self_station(state)
    if station is None:
        return frozenset()
    return frozenset(
        (pos.x, pos.y)
        for pos in BuildingFootprintResolver.cells(
            station,
            map_width=state.map_width,
            map_height=state.map_height,
        )
    )


def distance_to_station_footprint(target: Position | Cell, state: GameState) -> int | None:
    cells = station_footprint_cells(state)
    if not cells:
        return None
    xy = _cell(target)
    return min(chebyshev_distance(xy, cell) for cell in cells)


def station_defense_cells(state: GameState, *, ring_distance: int) -> frozenset[Cell]:
    """Return a clipped Chebyshev ring around the station footprint.

    Official defense template for a 2x2 base::

        222222
        211112
        210012
        210012
        211112
        222222

    Distance 0 is the station, distance 1 is weapon-build area, and distance 2
    is wall-build area.
    """
    if ring_distance < 0:
        return frozenset()
    footprint = station_footprint_cells(state)
    if not footprint:
        return frozenset()

    xs = [x for x, _ in footprint]
    ys = [y for _, y in footprint]
    min_x = min(xs) - ring_distance
    max_x = max(xs) + ring_distance
    min_y = min(ys) - ring_distance
    max_y = max(ys) + ring_distance

    cells: set[Cell] = set()
    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            if not (0 <= x < state.map_width and 0 <= y < state.map_height):
                continue
            if min(chebyshev_distance((x, y), cell) for cell in footprint) == ring_distance:
                cells.add((x, y))
    return frozenset(cells)


class BuildAreaPolicy(Protocol):
    """建造区域合法性的唯一抽象入口。

    当前生产实现：``StationDefenseBuildAreaPolicy``。它根据 2x2 Station footprint
    自动推导 Chebyshev ring：distance=1 为 weapon zone，distance=2 为 wall zone。
    Candidate、Legal、FinalValidator 都调用同一个 Policy，禁止三处各写一套区域逻辑。
    """

    def classify(
        self,
        *,
        target: Position | Cell,
        state: GameState,
    ) -> BuildAreaType: ...

    def permits(
        self,
        *,
        building_name: str,
        target: Position | Cell,
        state: GameState,
    ) -> bool: ...

    @property
    def has_verified_new_build_areas(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class StationDefenseBuildAreaPolicy:
    """Official 0/1/2 build template derived from our station footprint.

    The station-derived rings are the normal production source. Explicit
    cells/zone types remain as additive overrides for fixtures or future maps.
    """

    weapon_cells: frozenset[Cell] = field(default_factory=frozenset)
    wall_cells: frozenset[Cell] = field(default_factory=frozenset)
    weapon_zone_types: frozenset[str] = field(default_factory=frozenset)
    wall_zone_types: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_config(
        cls,
        *,
        weapon_cells: Iterable[Cell] = (),
        wall_cells: Iterable[Cell] = (),
        weapon_zone_types: Iterable[str] = (),
        wall_zone_types: Iterable[str] = (),
    ) -> "StationDefenseBuildAreaPolicy":
        return cls(
            weapon_cells=frozenset((int(x), int(y)) for x, y in weapon_cells),
            wall_cells=frozenset((int(x), int(y)) for x, y in wall_cells),
            weapon_zone_types=frozenset(str(v) for v in weapon_zone_types),
            wall_zone_types=frozenset(str(v) for v in wall_zone_types),
        )

    @property
    def has_verified_new_build_areas(self) -> bool:
        # Production can infer the 0/1/2 rings from an observed station. The
        # property describes the policy capability rather than current state.
        return True

    def classify(
        self,
        *,
        target: Position | Cell,
        state: GameState,
    ) -> BuildAreaType:
        xy = _cell(target)
        # 显式特殊地图配置比自动 Station ring 更具体，必须优先。否则一个
        # 测试/特殊地图明确声明为 wall 的 cell 可能因恰好落在默认 distance=1
        # 被错误分类为 weapon。
        if xy in self.weapon_cells or any(
            z.zone_type in self.weapon_zone_types
            and (z.position.x, z.position.y) == xy
            for z in state.neutral_zones
        ):
            return BuildAreaType.WEAPON

        if xy in self.wall_cells or any(
            z.zone_type in self.wall_zone_types
            and (z.position.x, z.position.y) == xy
            for z in state.neutral_zones
        ):
            return BuildAreaType.WALL

        distance = distance_to_station_footprint(xy, state)
        if distance == 0:
            return BuildAreaType.STATION
        if distance == 1:
            return BuildAreaType.WEAPON
        if distance == 2:
            return BuildAreaType.WALL

        return BuildAreaType.NONE

    def permits(
        self,
        *,
        building_name: str,
        target: Position | Cell,
        state: GameState,
    ) -> bool:
        name = building_name.lower()
        xy = _cell(target)

        # Official rules allow replacing an existing weapon. Its presence is
        # direct evidence that the position is a valid weapon-build cell.
        if name in WEAPON_TYPES:
            existing = next(
                (
                    b
                    for b in state.buildings
                    if b.owner == "self"
                    and (b.position.x, b.position.y) == xy
                ),
                None,
            )
            if existing is not None and existing.building_type in WEAPON_TYPES:
                return True
            return self.classify(target=xy, state=state) is BuildAreaType.WEAPON

        if name == "wall":
            return self.classify(target=xy, state=state) is BuildAreaType.WALL

        return False


# Backward-compatible name retained for callers/tests from V0.5.0 foundation.
VerifiedBuildAreaPolicy = StationDefenseBuildAreaPolicy
DEFAULT_BUILD_AREA_POLICY = StationDefenseBuildAreaPolicy()


def _station_bounds(state: GameState) -> tuple[int, int, int, int] | None:
    cells = station_footprint_cells(state)
    if not cells:
        return None
    xs = [x for x, _ in cells]
    ys = [y for _, y in cells]
    return min(xs), max(xs), min(ys), max(ys)


def station_front_side(state: GameState) -> str:
    """Return the side facing the map interior: ``right`` for a left-side base,
    ``left`` for a right-side base.

    The official mirrored spawn layout places one base in the left/top area and
    the other in the right/bottom area.  The x-axis is sufficient to identify
    which horizontal side faces the robot-spawn / map-interior direction.
    """
    bounds = _station_bounds(state)
    if bounds is None:
        return "right"
    min_x, max_x, _, _ = bounds
    station_center_x = (min_x + max_x) / 2.0
    map_center_x = (state.map_width - 1) / 2.0
    return "right" if station_center_x <= map_center_x else "left"


def wall_blueprint_cells(state: GameState) -> frozenset[Cell]:
    """Return the authoritative three-side wall blueprint (16 cells).

    Left/top spawn: TOP + BOTTOM + RIGHT, leaving the rear LEFT middle open.
    Right/bottom spawn: TOP + BOTTOM + LEFT, leaving the rear RIGHT middle open.

    Corners belong to TOP/BOTTOM, so a 6x6 outer ring contributes 6 + 6 + 4
    cells = 16 planned walls.
    """
    bounds = _station_bounds(state)
    if bounds is None:
        return frozenset()
    min_x, max_x, min_y, max_y = bounds
    outer_min_x, outer_max_x = min_x - 2, max_x + 2
    outer_min_y, outer_max_y = min_y - 2, max_y + 2
    cells = station_defense_cells(state, ring_distance=2)
    front = station_front_side(state)
    result = {
        cell for cell in cells
        if cell[1] in {outer_min_y, outer_max_y}
        or (front == "right" and cell[0] == outer_max_x)
        or (front == "left" and cell[0] == outer_min_x)
    }
    return frozenset(result)


def ordered_wall_build_cells(state: GameState) -> tuple[Cell, ...]:
    """Return the single authoritative build order for the 16-wall blueprint.

    Order:
    1. front-side middle four cells (fastest direct robot barrier),
    2. the two front corners,
    3. TOP/BOTTOM alternating from front toward the rear.

    Both the approach planner and BuildCandidateGenerator consume this exact
    order, preventing a Worker from walking to A and then building B.
    """
    blueprint = wall_blueprint_cells(state)
    bounds = _station_bounds(state)
    if not blueprint or bounds is None:
        return ()
    min_x, max_x, min_y, max_y = bounds
    outer_min_x, outer_max_x = min_x - 2, max_x + 2
    outer_min_y, outer_max_y = min_y - 2, max_y + 2
    front = station_front_side(state)
    front_x = outer_max_x if front == "right" else outer_min_x

    # Front middle excludes TOP/BOTTOM corner cells.
    front_middle = [
        (front_x, y)
        for y in range(outer_min_y + 1, outer_max_y)
        if (front_x, y) in blueprint
    ]
    # Start around station center, then expand vertically for early compact cover.
    station_center_y = (min_y + max_y) / 2.0
    front_middle.sort(key=lambda c: (abs(c[1] - station_center_y), c[1]))

    front_corners = [
        (front_x, outer_min_y),
        (front_x, outer_max_y),
    ]
    front_corners = [c for c in front_corners if c in blueprint]

    # Top/bottom remainder: from front toward rear, alternating rows.
    if front == "right":
        xs = range(outer_max_x - 1, outer_min_x - 1, -1)
    else:
        xs = range(outer_min_x + 1, outer_max_x + 1)
    remainder: list[Cell] = []
    for x in xs:
        top = (x, outer_max_y)
        bottom = (x, outer_min_y)
        if top in blueprint and top not in front_corners:
            remainder.append(top)
        if bottom in blueprint and bottom not in front_corners:
            remainder.append(bottom)

    ordered = tuple(front_middle + front_corners + remainder)
    # Defensive assertion kept local; malformed maps simply fall back to a
    # deterministic order instead of crashing production.
    if set(ordered) != set(blueprint):
        return tuple(sorted(blueprint))
    return ordered


def wall_blueprint_missing_cells(state: GameState) -> tuple[Cell, ...]:
    existing = {
        (b.position.x, b.position.y)
        for b in state.buildings
        if b.owner == "self" and b.building_type == "wall"
    }
    return tuple(cell for cell in ordered_wall_build_cells(state) if cell not in existing)


def wall_blueprint_missing_count(state: GameState) -> int:
    return len(wall_blueprint_missing_cells(state))


def wall_blueprint_complete(state: GameState) -> bool:
    blueprint = wall_blueprint_cells(state)
    return bool(blueprint) and wall_blueprint_missing_count(state) == 0


def wall_build_priority(state: GameState, target: Position | Cell) -> float:
    ordered = ordered_wall_build_cells(state)
    xy = _cell(target)
    if xy not in ordered or not ordered:
        return 0.0
    index = ordered.index(xy)
    if len(ordered) == 1:
        return 1.0
    return 1.0 - index / (len(ordered) - 1)


@dataclass(frozen=True, slots=True)
class RocketClusterPlan:
    """Three weapon cells sharing one fixed controller cell.

    Opening doctrine fills these cells with three Rockets. Existing mixed
    defenses are retained and count toward the same three-slot target.
    """

    controller: Cell
    rocket_cells: tuple[Cell, Cell, Cell]


def rocket_cluster_plan(state: GameState) -> RocketClusterPlan | None:
    """Derive a stable three-weapon cluster around one common control cell.

    The controller is chosen on the *rear* side of the weapon ring so the
    Pioneer can stand in a comparatively protected cell while the three weapon
    cells surround it.  For a top/left spawn we prefer the lower rear-middle
    cell; for a bottom/right spawn the upper rear-middle cell.  If clipping near
    a map edge invalidates that exact point, all weapon-ring cells are evaluated
    deterministically and the first cell with at least three adjacent weapon
    cells is used.
    """
    bounds = _station_bounds(state)
    weapon_ring = station_defense_cells(state, ring_distance=1)
    if bounds is None or len(weapon_ring) < 4:
        return None
    min_x, max_x, min_y, max_y = bounds
    front = station_front_side(state)
    rear_x = min_x - 1 if front == "right" else max_x + 1
    station_center_y = (min_y + max_y) / 2.0
    map_center_y = (state.map_height - 1) / 2.0
    preferred_y = min_y if station_center_y >= map_center_y else max_y
    preferred = (rear_x, preferred_y)
    existing = {
        (b.position.x, b.position.y) for b in state.buildings
        if b.owner == "self" and b.building_type in WEAPON_TYPES
    }
    terrain = TraversabilityMap.from_state(state)
    # Ignore transient actors/robots when fixing the layout, but avoid static
    # blockers. Keep already-built weapons in the same common-control cluster.
    static_blocked = (terrain.resource_cells | terrain.neutral_cells | terrain.building_cells) - existing

    def adjacent_weapon_cells(controller: Cell) -> tuple[Cell, ...]:
        cx, cy = controller
        candidates = [
            cell for cell in weapon_ring
            if cell != controller and chebyshev_distance(controller, cell) <= 1
            and cell not in static_blocked
        ]
        # Prefer cells facing map interior, then compact/stable coordinates.
        map_center_x = (state.map_width - 1) / 2.0
        map_center_y2 = (state.map_height - 1) / 2.0
        candidates.sort(key=lambda c: (
            c not in existing,
            max(abs(c[0] - map_center_x), abs(c[1] - map_center_y2)),
            abs(c[0] - map_center_x) + abs(c[1] - map_center_y2),
            c[0], c[1],
        ))
        return tuple(candidates)

    candidates = [preferred] + sorted(
        (cell for cell in weapon_ring if cell != preferred),
        key=lambda c: (
            chebyshev_distance(c, preferred),
            c[0], c[1],
        ),
    )
    for controller in candidates:
        if controller in static_blocked or controller in existing:
            continue
        rockets = adjacent_weapon_cells(controller)
        if len(rockets) >= 3 and existing.issubset(set(rockets[:3])):
            return RocketClusterPlan(controller=controller, rocket_cells=tuple(rockets[:3]))
    return None


def ordered_weapon_build_cells(state: GameState) -> tuple[Cell, ...]:
    """Return weapon cells with the fixed three-weapon cluster first."""
    cells = station_defense_cells(state, ring_distance=1)
    if not cells:
        return ()
    plan = rocket_cluster_plan(state)
    cluster = tuple(plan.rocket_cells) if plan is not None else ()
    remaining = [cell for cell in cells if cell not in cluster and (plan is None or cell != plan.controller)]
    center_x = (state.map_width - 1) / 2.0
    center_y = (state.map_height - 1) / 2.0
    remaining.sort(key=lambda cell: (
        max(abs(cell[0] - center_x), abs(cell[1] - center_y)),
        abs(cell[0] - center_x) + abs(cell[1] - center_y),
        cell[0], cell[1],
    ))
    return cluster + tuple(remaining)


def weapon_build_priority(state: GameState, target: Position | Cell) -> float:
    ordered = ordered_weapon_build_cells(state)
    xy = _cell(target)
    if xy not in ordered or not ordered:
        return 0.0
    index = ordered.index(xy)
    if len(ordered) == 1:
        return 1.0
    return 1.0 - index / (len(ordered) - 1)
