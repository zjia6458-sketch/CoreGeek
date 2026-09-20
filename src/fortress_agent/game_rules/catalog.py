from __future__ import annotations

from dataclasses import dataclass

RESOURCE_TYPES = frozenset({"stone", "iron", "copper"})
WEAPON_TYPES = frozenset({"gatling", "railgun", "rocket"})

# Default strategy preference, not a protocol legality rule.
DEFAULT_FIRST_WEAPON_TYPE = "rocket"
TASK_ZONE_TYPES = frozenset({
    "challengerTaskPoint1",
    "challengerTaskPoint2",
    "defenderTaskPoint1",
    "defenderTaskPoint2",
})
NEUTRAL_BLOCKER_TYPES = frozenset({
    "vendor",
    "weaponShop",
    *RESOURCE_TYPES,
    *TASK_ZONE_TYPES,
})


@dataclass(frozen=True, slots=True)
class BuildingRule:
    building_type: str
    max_count: int
    build_gold_cost: int = 0
    build_items: tuple[tuple[str, int], ...] = ()
    allowed_builder: str = "worker"
    daytime_only: bool = True


_BUILDING_RULES = {
    "station": BuildingRule("station", 1),
    "gatling": BuildingRule("gatling", 3, build_gold_cost=25),
    "railgun": BuildingRule("railgun", 3, build_gold_cost=25),
    "rocket": BuildingRule("rocket", 3, build_gold_cost=25),
    "wall": BuildingRule("wall", 20, build_items=(("stone", 1),)),
}

_MAX_HP = {
    "station": {1: 1500, 2: 3000, 3: 4500},
    "gatling": {1: 1000, 2: 1500, 3: 2000},
    "railgun": {1: 1000, 2: 1500, 3: 2000},
    "rocket": {1: 1000, 2: 1500, 3: 2000},
    "wall": {1: 1000, 2: 1500, 3: 2000},
}

_ATTACK_RANGE = {
    "gatling": {1: 3, 2: 5, 3: 7},
    "railgun": {1: 6, 2: 8, 3: 10},
    "rocket": {1: 10, 2: 15, 3: None},  # None = full map
}


def building_rule(building_type: str) -> BuildingRule | None:
    return _BUILDING_RULES.get(str(building_type).strip().lower())


def building_max_hp(building_type: str, level: int | None) -> int | None:
    levels = _MAX_HP.get(str(building_type).strip().lower())
    if levels is None:
        return None
    return levels.get(max(1, int(level or 1)))


def weapon_attack_range(building_type: str, level: int | None) -> int | None:
    levels = _ATTACK_RANGE.get(str(building_type).strip().lower())
    if levels is None:
        return None
    return levels.get(max(1, int(level or 1)))


def weapon_level_damage(building_type: str, level: int | None) -> int:
    t = str(building_type).strip().lower()
    lv = max(1, int(level or 1))
    if t == "gatling":
        return 10
    if t == "railgun":
        return 10 * lv
    if t == "rocket":
        return 20
    return 0


@dataclass(frozen=True, slots=True)
class CharacterRule:
    role_type: str
    max_hp: int
    backpack_capacity: int
    initial_count: int


@dataclass(frozen=True, slots=True)
class RobotRule:
    robot_type: str
    attack: int
    attack_range: int
    max_hp: int
    score_value: int


CHARACTER_RULES = {
    "pioneer": CharacterRule("pioneer", 200, 40, 1),
    "worker": CharacterRule("worker", 220, 100, 2),
}

ROBOT_RULES = {
    "smallrobot": RobotRule("smallrobot", 5, 3, 40, 1),
    "middlerobot": RobotRule("middlerobot", 10, 3, 60, 2),
    "largerobot": RobotRule("largerobot", 20, 3, 500, 4),
    "bossrobot": RobotRule("bossrobot", 40, 3, 800, 10),
}

# Known fixed WeaponShop prices. The live weaponShopList remains authoritative
# for actual availability and price; these values are useful for planning and
# consistency checks, not for fabricating a missing shop item.
KNOWN_WEAPON_SHOP_PRICES = {
    "WeaponUpgradeVoucher1": 100,
    "WallUpgradeVoucher1": 20,
    "StationUpgradeVoucher1": 100,
    "WeaponUpgradeVoucher2": 150,
    "WallUpgradeVoucher2": 30,
    "StationUpgradeVoucher2": 150,
    "WallFixer": 10,
    "Medicine": 10,
    "DizzyWeapon": 100,
    "Bomb": 100,
    "SmallRobotSummonOrder": 20,
    "MiddleRobotSummonOrder": 30,
    "LargeRobotSummonOrder": 100,
    "BossRobotSummonOrder": 200,
}
