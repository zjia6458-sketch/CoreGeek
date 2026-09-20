"""夜间时间感知安全寻路与机器人威胁场。"""
from __future__ import annotations

from dataclasses import dataclass
import heapq
from math import inf
from typing import Iterable

from fortress_agent.domain.state import GameState, Position
from fortress_agent.game_rules.build_area import station_footprint_cells
from fortress_agent.game_rules.geometry import chebyshev_distance, neighbors8
from fortress_agent.memory.robot_trajectory import RobotTrajectoryMemoryView
from fortress_agent.memory.world import WorldMemoryView
from fortress_agent.safety.deadline import DeadlineView
from fortress_agent.world.pathfinding import NavigationPolicy, PathResult
from fortress_agent.world.traversability import TraversabilityMap


@dataclass(frozen=True, slots=True)
class RobotThreatConfig:
    prediction_horizon: int = 12
    observed_heading_steps: int = 3
    hard_safety_margin: int = 1
    soft_safety_margin: int = 3


class RobotThreatField:
    """保守的未来机器人风险估计。

    对每个机器人同时计算：
    A) 每回合向己方 Station footprint 收缩的最快路径；
    B) 最近真实 heading 延续若干步后再向 Station 收缩的路径。
    两者风险取最大值。我们不声称复刻判题器内部机器人寻路器。
    """

    def __init__(
        self,
        state: GameState,
        trajectory: RobotTrajectoryMemoryView | None,
        config: RobotThreatConfig,
    ) -> None:
        self.state = state
        self.trajectory = trajectory
        self.config = config
        self._station_cells = tuple(station_footprint_cells(state))
        self._routes: dict[str, tuple[tuple[Position, ...], tuple[Position, ...]]] = {}
        for enemy in state.enemies:
            if enemy.hp <= 0:
                continue
            route_a = self._station_route(enemy.position, config.prediction_horizon)
            heading = trajectory.heading(enemy.enemy_id) if trajectory is not None else None
            route_b = self._heading_route(enemy.position, heading, config)
            self._routes[str(enemy.enemy_id)] = (route_a, route_b)

    @staticmethod
    def _sign(value: int) -> int:
        return 0 if value == 0 else (1 if value > 0 else -1)

    def _nearest_station_cell(self, pos: Position) -> Position | None:
        if not self._station_cells:
            return None
        x, y = min(
            self._station_cells,
            key=lambda cell: (chebyshev_distance((pos.x, pos.y), cell), cell[0], cell[1]),
        )
        return Position(x, y)

    def _step_toward_station(self, pos: Position) -> Position:
        goal = self._nearest_station_cell(pos)
        if goal is None:
            return pos
        nx = pos.x + self._sign(goal.x - pos.x)
        ny = pos.y + self._sign(goal.y - pos.y)
        nx = min(max(0, nx), self.state.map_width - 1)
        ny = min(max(0, ny), self.state.map_height - 1)
        return Position(nx, ny)

    def _station_route(self, start: Position, horizon: int) -> tuple[Position, ...]:
        route = [start]
        current = start
        for _ in range(max(0, horizon)):
            current = self._step_toward_station(current)
            route.append(current)
        return tuple(route)

    def _heading_route(
        self,
        start: Position,
        heading: tuple[int, int] | None,
        config: RobotThreatConfig,
    ) -> tuple[Position, ...]:
        route = [start]
        current = start
        for eta in range(1, max(0, config.prediction_horizon) + 1):
            if heading is not None and eta <= max(0, config.observed_heading_steps):
                nx = min(max(0, current.x + heading[0]), self.state.map_width - 1)
                ny = min(max(0, current.y + heading[1]), self.state.map_height - 1)
                current = Position(nx, ny)
            else:
                current = self._step_toward_station(current)
            route.append(current)
        return tuple(route)

    def _enemy_at(self, enemy_id: str, eta: int, route: tuple[Position, ...]) -> Position:
        return route[min(max(0, eta), len(route) - 1)]

    def risk(self, pos: Position, eta: int) -> float:
        risk = 0.0
        for enemy in self.state.enemies:
            if enemy.hp <= 0:
                continue
            routes = self._routes.get(str(enemy.enemy_id))
            if routes is None:
                continue
            attack_range = max(0, int(enemy.attack_range or 3))
            hard = attack_range + max(0, self.config.hard_safety_margin)
            soft = attack_range + max(hard, self.config.soft_safety_margin)
            for route in routes:
                predicted = self._enemy_at(str(enemy.enemy_id), eta, route)
                distance = chebyshev_distance(pos, predicted)
                if distance <= hard:
                    local = 1.0
                elif distance <= soft:
                    span = max(1, soft - hard)
                    local = max(0.0, 1.0 - (distance - hard) / (span + 1.0))
                else:
                    local = 0.0
                risk = max(risk, local)
        return risk

    def safe_for_window(self, pos: Position, *, start_eta: int, rounds: int, max_risk: float) -> bool:
        return all(
            self.risk(pos, start_eta + offset) <= max_risk
            for offset in range(max(0, rounds) + 1)
        )


class SafePathPlanner:
    """A* whose state includes ETA, making future robot positions observable."""

    def __init__(
        self,
        *,
        width: int,
        height: int,
        threat: RobotThreatField,
        threat_weight: float = 6.0,
        hard_risk_threshold: float = 1.0,
        unknown_cost: float = 1.5,
        max_steps: int = 64,
        max_expansions: int = 4096,
    ) -> None:
        self.width = width
        self.height = height
        self.threat = threat
        self.threat_weight = max(0.0, float(threat_weight))
        self.hard_risk_threshold = float(hard_risk_threshold)
        self.unknown_cost = max(0.0, float(unknown_cost))
        self.max_steps = max(1, int(max_steps))
        self.max_expansions = max(64, int(max_expansions))

    def find_path_to_any(
        self,
        memory: WorldMemoryView,
        start: Position,
        goals: Iterable[Position],
        *,
        traversability: TraversabilityMap,
        policy: NavigationPolicy = NavigationPolicy.ALLOW_UNKNOWN,
        deadline: DeadlineView | None = None,
        deadline_reserve_seconds: float = 0.45,
        start_eta: int = 0,
    ) -> PathResult:
        goal_set = {
            (g.x, g.y) for g in goals
            if traversability.inside(g.x, g.y) and traversability.is_walkable(g.x, g.y)
        }
        if not goal_set:
            return PathResult(False, (), inf)
        start_key = (start.x, start.y, max(0, int(start_eta)))
        if (start.x, start.y) in goal_set:
            return PathResult(True, (start,), 0.0)

        frontier: list[tuple[float, int, int, int, int]] = []
        serial = 0
        heapq.heappush(frontier, (self._heuristic(start.x, start.y, goal_set), serial, start.x, start.y, start_key[2]))
        came: dict[tuple[int, int, int], tuple[int, int, int] | None] = {start_key: None}
        cost: dict[tuple[int, int, int], float] = {start_key: 0.0}
        reached: tuple[int, int, int] | None = None
        expansions = 0

        while frontier:
            if expansions % 32 == 0 and deadline is not None and deadline.remaining() <= deadline_reserve_seconds:
                return PathResult(False, (), inf)
            if expansions >= self.max_expansions:
                return PathResult(False, (), inf)
            _, _, x, y, eta = heapq.heappop(frontier)
            expansions += 1
            if (x, y) in goal_set:
                reached = (x, y, eta)
                break
            if eta - start_key[2] >= self.max_steps:
                continue
            for nx, ny in neighbors8(x, y):
                if not traversability.inside(nx, ny) or not traversability.is_walkable(nx, ny):
                    continue
                cell = memory.cell(nx, ny)
                if policy is NavigationPolicy.KNOWN_ONLY and not cell.discovered:
                    continue
                next_eta = eta + 1
                risk = self.threat.risk(Position(nx, ny), next_eta)
                if risk >= self.hard_risk_threshold:
                    continue
                step_cost = 1.0 + risk * self.threat_weight
                if not cell.discovered:
                    step_cost += self.unknown_cost
                new_cost = cost[(x, y, eta)] + step_cost
                key = (nx, ny, next_eta)
                if key in cost and new_cost >= cost[key]:
                    continue
                cost[key] = new_cost
                came[key] = (x, y, eta)
                serial += 1
                heapq.heappush(frontier, (
                    new_cost + self._heuristic(nx, ny, goal_set),
                    serial, nx, ny, next_eta,
                ))

        if reached is None:
            return PathResult(False, (), inf)
        reverse: list[Position] = []
        cur: tuple[int, int, int] | None = reached
        while cur is not None:
            reverse.append(Position(cur[0], cur[1]))
            cur = came[cur]
        reverse.reverse()
        return PathResult(True, tuple(reverse), cost[reached])

    @staticmethod
    def _heuristic(x: int, y: int, goals: set[tuple[int, int]]) -> int:
        return min(chebyshev_distance((x, y), goal) for goal in goals)
