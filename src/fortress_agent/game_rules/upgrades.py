"""确定性的防御升级/维修目标规划。"""
from __future__ import annotations

from dataclasses import dataclass

from fortress_agent.domain.state import BuildingState, Position
from fortress_agent.game_rules.build_area import (
    station_front_side,
    wall_blueprint_cells,
)
from fortress_agent.game_rules.catalog import WEAPON_TYPES


@dataclass(frozen=True, slots=True)
class UpgradeTarget:
    voucher_name: str
    building_id: str
    position: Position
    stage: str


def _own(state, types: set[str]) -> list[BuildingState]:
    return sorted(
        [b for b in state.buildings if b.owner == "self" and b.building_type in types],
        key=lambda b: str(b.building_id),
    )


def _first_level(buildings: list[BuildingState], level: int) -> BuildingState | None:
    return next((b for b in buildings if int(b.level or 1) == level), None)


def _front_wall_cells(state) -> set[tuple[int, int]]:
    blueprint = wall_blueprint_cells(state)
    if not blueprint:
        return set()
    front = station_front_side(state)
    xs = [x for x, _ in blueprint]
    front_x = max(xs) if front == "right" else min(xs)
    return {(x, y) for x, y in blueprint if x == front_x}


def next_upgrade_target(state) -> UpgradeTarget | None:
    """Apply the frozen upgrade sequence from the team doctrine.

    1. all weapons -> L2
    2. existing front-side walls -> L2
    3. all weapons -> L3
    4. existing front-side walls -> L3
    5. Station -> L2
    6. Station -> L3
    7. top/bottom walls -> L2
    8. top/bottom walls -> L3
    9. legacy rear-side walls -> L2, then L3
    """
    weapons = _own(state, set(WEAPON_TYPES))
    station = _own(state, {"station"})
    walls = _own(state, {"wall"})
    # Core facilities may be upgraded as soon as the three weapon slots are
    # filled. Requiring every wall first can deadlock progression when stone is
    # scarce. Existing front walls also upgrade without waiting for other sides.
    if len(weapons) < 3:
        return None

    target = _first_level(weapons, 1)
    if target is not None:
        return UpgradeTarget("WeaponUpgradeVoucher1", str(target.building_id), target.position, "weapons_to_2")

    front_cells = _front_wall_cells(state)
    front_walls = [b for b in walls if (b.position.x, b.position.y) in front_cells]
    blueprint = wall_blueprint_cells(state)
    other_walls = [b for b in walls if (b.position.x, b.position.y) in blueprint - front_cells]
    rear_walls = [b for b in walls if (b.position.x, b.position.y) not in blueprint]

    target = _first_level(front_walls, 1)
    if target is not None:
        return UpgradeTarget("WallUpgradeVoucher1", str(target.building_id), target.position, "front_walls_to_2")

    target = _first_level(weapons, 2)
    if target is not None:
        return UpgradeTarget("WeaponUpgradeVoucher2", str(target.building_id), target.position, "weapons_to_3")

    target = _first_level(front_walls, 2)
    if target is not None:
        return UpgradeTarget("WallUpgradeVoucher2", str(target.building_id), target.position, "front_walls_to_3")

    if station and int(station[0].level or 1) == 1:
        b = station[0]
        return UpgradeTarget("StationUpgradeVoucher1", str(b.building_id), b.position, "station_to_2")
    if station and int(station[0].level or 1) == 2:
        b = station[0]
        return UpgradeTarget("StationUpgradeVoucher2", str(b.building_id), b.position, "station_to_3")

    target = _first_level(other_walls, 1)
    if target is not None:
        return UpgradeTarget("WallUpgradeVoucher1", str(target.building_id), target.position, "other_walls_to_2")
    target = _first_level(other_walls, 2)
    if target is not None:
        return UpgradeTarget("WallUpgradeVoucher2", str(target.building_id), target.position, "other_walls_to_3")
    for level in (1, 2):
        target = _first_level(rear_walls, level)
        if target is not None:
            return UpgradeTarget(f"WallUpgradeVoucher{level}", str(target.building_id), target.position, f"rear_walls_to_{level + 1}")
    return None
