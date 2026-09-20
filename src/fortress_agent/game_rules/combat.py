"""战斗规则与可复用伤害估计。

本模块只放“官方规则可确定”的几何/伤害语义，供 Candidate 与 Reward 共用：
Rocket AOE、Gatling 最近弹道目标、Railgun 能量穿透。策略偏好不应写在这里。
"""
from __future__ import annotations

from collections import defaultdict

from fortress_agent.domain.state import GameState, Position
from fortress_agent.game_rules.catalog import weapon_level_damage, weapon_attack_range
from fortress_agent.game_rules.geometry import chebyshev_distance, neighbors8


def _station_position(state: GameState) -> Position | None:
    station = next((b for b in state.buildings if b.owner == "self" and b.building_type == "station"), None)
    return station.position if station is not None else None


def _threat_weight(state: GameState, enemy) -> float:
    station = _station_position(state)
    distance = chebyshev_distance(enemy.position, station) if station is not None else 10
    return float(enemy.attack or 1) / max(1.0, distance + 1.0)


def _line_enemies(state: GameState, origin: Position, target: Position):
    """返回中心连线线段上的存活机器人，按离武器从近到远排序。"""
    dx = target.x - origin.x
    dy = target.y - origin.y
    if dx == 0 and dy == 0:
        return ()
    items = []
    for enemy in state.enemies:
        if enemy.hp <= 0:
            continue
        px = enemy.position.x - origin.x
        py = enemy.position.y - origin.y
        # 两个向量叉积为 0 => 三点共线；点积范围保证机器人位于射线终点之前。
        if dx * py - dy * px != 0:
            continue
        dot = px * dx + py * dy
        limit = dx * dx + dy * dy
        if dot < 0 or dot > limit:
            continue
        items.append((px * px + py * py, str(enemy.enemy_id), enemy))
    return tuple(item[2] for item in sorted(items))


def estimate_attack_value(state: GameState, weapon, targets: tuple[Position, ...]) -> tuple[float, float]:
    """返回 ``(kill_score, survival_value)``。

    三种武器均按正式规则估计：
    - Rocket：中心20、8邻域10，多弹叠加；
    - Gatling：每条目标弹道命中最近机器人，每弹10；
    - Railgun：能量 10/20/30 沿中心连线按距离顺序穿透并衰减。
    """
    alive = [e for e in state.enemies if e.hp > 0]
    damage_by_enemy: dict[str, float] = defaultdict(float)
    wtype = weapon.building_type

    if wtype == "rocket":
        for impact in targets:
            for enemy in alive:
                d = chebyshev_distance(enemy.position, impact)
                if d == 0:
                    damage_by_enemy[str(enemy.enemy_id)] += 20.0
                elif d == 1:
                    damage_by_enemy[str(enemy.enemy_id)] += 10.0

    elif wtype == "gatling":
        for target in targets:
            line = _line_enemies(state, weapon.position, target)
            if line:
                damage_by_enemy[str(line[0].enemy_id)] += 10.0

    elif wtype == "railgun":
        energy = float(weapon_level_damage("railgun", weapon.level))
        if targets:
            for enemy in _line_enemies(state, weapon.position, targets[0]):
                if energy <= 0:
                    break
                already = damage_by_enemy[str(enemy.enemy_id)]
                remaining_hp = max(0.0, float(enemy.hp) - already)
                dealt = min(energy, remaining_hp)
                if dealt <= 0:
                    continue
                damage_by_enemy[str(enemy.enemy_id)] += dealt
                energy -= dealt

    score = 0.0
    survival = 0.0
    for enemy in alive:
        damage = min(float(enemy.hp), damage_by_enemy.get(str(enemy.enemy_id), 0.0))
        if damage <= 0:
            continue
        survival += damage * _threat_weight(state, enemy)
        if damage >= enemy.hp:
            score += float(enemy.score_value or 0)
    return score, survival


def best_rocket_targets(state: GameState, weapon, *, target_count: int) -> tuple[Position, ...]:
    """为 Rocket 选择最多 ``target_count`` 个互异 AOE 落点。"""
    if target_count <= 0:
        return ()
    candidates: set[tuple[int, int]] = set()
    official_range = weapon_attack_range("rocket", weapon.level)
    server_range = int(weapon.attack_range or 0)
    effective_range = None if official_range is None else (int(official_range) if server_range <= 0 else min(server_range, int(official_range)))
    for enemy in state.enemies:
        if enemy.hp <= 0:
            continue
        for x, y in [(enemy.position.x, enemy.position.y), *neighbors8(enemy.position.x, enemy.position.y)]:
            if not (0 <= x < state.map_width and 0 <= y < state.map_height):
                continue
            if effective_range is not None and chebyshev_distance(weapon.position, (x, y)) > effective_range:
                continue
            candidates.add((x, y))
    if not candidates:
        return ()

    selected: list[Position] = []
    for _ in range(target_count):
        best = None
        best_value = float("-inf")
        for x, y in sorted(candidates):
            if any(p.x == x and p.y == y for p in selected):
                continue
            trial = tuple([*selected, Position(x, y)])
            score, survival = estimate_attack_value(state, weapon, trial)
            value = score * 8.0 + survival
            if value > best_value:
                best_value = value
                best = Position(x, y)
        if best is None:
            break
        selected.append(best)
    return tuple(selected)
