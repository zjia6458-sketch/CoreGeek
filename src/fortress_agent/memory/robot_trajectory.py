"""跨回合机器人轨迹记忆。

只保存最近少量真实观测位置，用于夜间威胁预测。它不是 WorldMemory 的长期事实，
不会写磁盘，也不会参与协议/合法性判断；进程重启后安全丢失。
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from fortress_agent.domain.state import Position


@dataclass(frozen=True, slots=True)
class RobotTrajectoryMemoryView:
    positions_by_robot: Mapping[str, tuple[Position, ...]]

    def positions(self, robot_id) -> tuple[Position, ...]:
        return self.positions_by_robot.get(str(robot_id), ())

    def heading(self, robot_id) -> tuple[int, int] | None:
        points = self.positions(robot_id)
        if len(points) < 2:
            return None
        a, b = points[-2], points[-1]
        dx = 0 if b.x == a.x else (1 if b.x > a.x else -1)
        dy = 0 if b.y == a.y else (1 if b.y > a.y else -1)
        if dx == 0 and dy == 0:
            return None
        return dx, dy


class RobotTrajectoryMemory:
    def __init__(self, *, max_points: int = 4) -> None:
        self._max_points = max(2, int(max_points))
        self._positions: dict[str, list[Position]] = {}

    def observe(self, state) -> None:
        alive = set()
        for enemy in state.enemies:
            if enemy.hp <= 0:
                continue
            rid = str(enemy.enemy_id)
            alive.add(rid)
            history = self._positions.setdefault(rid, [])
            pos = Position(enemy.position.x, enemy.position.y)
            if not history or history[-1] != pos:
                history.append(pos)
                if len(history) > self._max_points:
                    del history[:-self._max_points]
        # Robots disappear at dawn/death. Stale history should not influence a
        # different later robot reusing an id.
        for rid in tuple(self._positions):
            if rid not in alive:
                self._positions.pop(rid, None)

    def view(self) -> RobotTrajectoryMemoryView:
        return RobotTrajectoryMemoryView(
            positions_by_robot=MappingProxyType({
                rid: tuple(points) for rid, points in self._positions.items()
            })
        )
