from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import heapq
from typing import Iterable

from fortress_agent.domain.state import Position
from fortress_agent.game_rules.geometry import chebyshev_distance, neighbors8
from fortress_agent.memory.world import WorldMemoryView
from fortress_agent.safety.deadline import DeadlineView
from fortress_agent.world.traversability import TraversabilityMap


class NavigationPolicy(str, Enum):
    """路径规划时对未知格子的处理方式。"""

    KNOWN_ONLY = "known_only"
    ALLOW_UNKNOWN = "allow_unknown"


@dataclass(frozen=True, slots=True)
class PathResult:
    """A* 的不可变返回值。"""

    found: bool
    path: tuple[Position, ...]
    cost: float

    @property
    def steps(self) -> int:
        return max(0, len(self.path) - 1)


class AStarPathfinder:
    """面向 8 方向移动规则的 A* 路径规划器。

    设计要点：
    1. 正交/对角移动都只消耗 1 个游戏回合，因此步长成本相同；
    2. 启发函数使用 Chebyshev distance；
    3. ``find_path_to_any`` 使用**一次多目标 A***，不再对每个候选终点
       重复搜索整张地图；
    4. 支持 Deadline 与 expansion 上限，路径规划不能吞掉整个 5 秒响应预算。

    主要调用位置：
    - ``candidates/basic.py``：Worker 接近资源；
    - ``candidates/navigation.py``：任务点、Vendor、WeaponShop、BaseReturn。
    """

    def __init__(
        self,
        *,
        width: int = 41,
        height: int = 32,
        unknown_cost: float = 1.5,
        max_expansions: int = 4096,
    ) -> None:
        self.width = width
        self.height = height
        self.unknown_cost = unknown_cost
        self.max_expansions = max(64, int(max_expansions))

    def find_path(
        self,
        memory: WorldMemoryView,
        start: Position,
        goal: Position,
        *,
        policy: NavigationPolicy = NavigationPolicy.ALLOW_UNKNOWN,
        extra_cost: dict[tuple[int, int], float] | None = None,
        traversability: TraversabilityMap | None = None,
        deadline: DeadlineView | None = None,
        deadline_reserve_seconds: float = 0.45,
    ) -> PathResult:
        return self.find_path_to_any(
            memory,
            start,
            (goal,),
            policy=policy,
            extra_cost=extra_cost,
            traversability=traversability,
            deadline=deadline,
            deadline_reserve_seconds=deadline_reserve_seconds,
        )

    def find_path_to_any(
        self,
        memory: WorldMemoryView,
        start: Position,
        goals: Iterable[Position],
        *,
        policy: NavigationPolicy = NavigationPolicy.ALLOW_UNKNOWN,
        extra_cost: dict[tuple[int, int], float] | None = None,
        traversability: TraversabilityMap | None = None,
        deadline: DeadlineView | None = None,
        deadline_reserve_seconds: float = 0.45,
    ) -> PathResult:
        """一次 A* 搜索到达任意目标。

        旧实现会 ``for goal in goals`` 重复跑完整 A*。资源周围通常存在多个可交互
        access cell，多个 Worker/资源叠加后会放大为数百次地图搜索。现在把目标集合
        合并，在同一个 frontier 中搜索，最先以最小代价到达任一目标即结束。
        """

        unique_goals = tuple(sorted(
            {
                (goal.x, goal.y)
                for goal in goals
                if self._inside(goal.x, goal.y, traversability)
                and (
                    traversability is None
                    or traversability.is_walkable(goal.x, goal.y)
                )
            },
            key=lambda item: (item[0], item[1]),
        ))
        if not unique_goals:
            return PathResult(False, (), float("inf"))

        start_key = (start.x, start.y)
        goal_set = set(unique_goals)
        if start_key in goal_set:
            return PathResult(True, (start,), 0.0)

        extra_cost = extra_cost or {}
        frontier: list[tuple[float, int, int, int]] = []
        serial = 0
        heapq.heappush(
            frontier,
            (
                self._heuristic_to_any(start.x, start.y, unique_goals),
                serial,
                start.x,
                start.y,
            ),
        )
        came_from: dict[tuple[int, int], tuple[int, int] | None] = {
            start_key: None,
        }
        cost_so_far: dict[tuple[int, int], float] = {start_key: 0.0}

        reached: tuple[int, int] | None = None
        expansions = 0

        while frontier:
            # 每 32 次展开检查一次预算，避免在高密度障碍地图上长期占用回合。
            if expansions % 32 == 0 and deadline is not None:
                if deadline.remaining() <= max(0.0, deadline_reserve_seconds):
                    return PathResult(False, (), float("inf"))
            if expansions >= self.max_expansions:
                return PathResult(False, (), float("inf"))

            _, _, x, y = heapq.heappop(frontier)
            expansions += 1

            if (x, y) in goal_set:
                reached = (x, y)
                break

            for nx, ny in neighbors8(x, y):
                if not self._inside(nx, ny, traversability):
                    continue
                if traversability is not None and not traversability.is_walkable(nx, ny):
                    continue

                cell = memory.cell(nx, ny)
                if policy is NavigationPolicy.KNOWN_ONLY and not cell.discovered:
                    continue

                # 正交/对角移动在正式规则中都恰好消耗 1 回合。
                step_cost = 1.0
                if not cell.discovered:
                    step_cost += self.unknown_cost
                step_cost += max(0.0, float(extra_cost.get((nx, ny), 0.0)))

                new_cost = cost_so_far[(x, y)] + step_cost
                key = (nx, ny)
                if key in cost_so_far and new_cost >= cost_so_far[key]:
                    continue

                cost_so_far[key] = new_cost
                came_from[key] = (x, y)
                serial += 1
                priority = new_cost + self._heuristic_to_any(
                    nx,
                    ny,
                    unique_goals,
                )
                heapq.heappush(frontier, (priority, serial, nx, ny))

        if reached is None:
            return PathResult(False, (), float("inf"))

        reverse_path: list[Position] = []
        current: tuple[int, int] | None = reached
        while current is not None:
            reverse_path.append(Position(*current))
            current = came_from[current]
        reverse_path.reverse()

        return PathResult(
            True,
            tuple(reverse_path),
            cost_so_far[reached],
        )

    @staticmethod
    def _heuristic_to_any(
        x: int,
        y: int,
        goals: tuple[tuple[int, int], ...],
    ) -> int:
        return min(
            chebyshev_distance((x, y), goal)
            for goal in goals
        )

    def _inside(
        self,
        x: int,
        y: int,
        traversability: TraversabilityMap | None,
    ) -> bool:
        if traversability is not None:
            return traversability.inside(x, y)
        return 0 <= x < self.width and 0 <= y < self.height
