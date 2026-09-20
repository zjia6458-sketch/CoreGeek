from __future__ import annotations

from fortress_agent.domain.state import Position, TaskState


def own_task_zones(state):
    prefix = (state.team_type or "").strip().lower()
    return tuple(
        zone
        for zone in state.neutral_zones
        if "taskpoint" in zone.zone_type.lower()
        and (not prefix or zone.zone_type.lower().startswith(prefix))
    )


def task_zone_positions_for_task(state, task: TaskState) -> tuple[Position, ...]:
    """Resolve the physical TaskPoint cells belonging to a task record.

    TaskPoint2 occupies two cells. The protocol task record exposes one
    taskPosition, so when that position matches a neutral-zone cell we expand
    to every own zone cell with the same TaskPoint type.
    """
    if task.position is None:
        return ()
    zones = own_task_zones(state)
    exact = next(
        (
            zone
            for zone in zones
            if zone.position.x == task.position.x and zone.position.y == task.position.y
        ),
        None,
    )
    if exact is not None:
        return tuple(
            zone.position
            for zone in zones
            if zone.zone_type == exact.zone_type
        )
    # Fallback to the explicit taskPosition if a server version omits the
    # neutral-zone entry.
    return (task.position,)


def available_task_zone_positions(state) -> tuple[Position, ...]:
    positions: dict[tuple[int, int], Position] = {}
    for task in state.tasks:
        if task.status != "available":
            continue
        for pos in task_zone_positions_for_task(state, task):
            positions[(pos.x, pos.y)] = pos
    return tuple(positions[key] for key in sorted(positions))


def active_task_anchor_positions(state) -> tuple[Position, ...]:
    """返回当前活跃自进化任务必须保持邻接的 TaskPoint 单元格。

    ``phaseTask`` 只告诉我们当前确实存在已领取任务，并不直接携带 task-point id。
    领取任务后开拓者必须始终停留在原任务点周围 1 格，因此最可靠的运行时锚点
    是：从“己方 TaskPoint 分组”中找到当前 Pioneer 仍然邻接的那一组。

    如果接口状态出现短暂不一致（例如 phaseTask 非空但 Pioneer 已不邻接任何任务点），
    返回空元组。调用方应采取保守策略：不要再生成 Pioneer 的普通移动，而不是
    猜测另一个 TaskPoint。
    """
    if not state.phase_task.strip():
        return ()
    pioneer = next((a for a in state.characters if a.role == "pioneer" and a.hp > 0), None)
    if pioneer is None:
        return ()

    zones = own_task_zones(state)
    adjacent = tuple(
        zone for zone in zones
        if max(abs(zone.position.x - pioneer.position.x), abs(zone.position.y - pioneer.position.y)) == 1
    )
    if not adjacent:
        return ()

    # TaskPoint2 可能占两个格子；一旦命中其中一个格子，就扩展到相同 terrain type
    # 的整组物理任务点，后续允许 Pioneer 在该任务点周围合法微调，但不能漂移到
    # 另一个 TaskPoint。
    zone_type = adjacent[0].zone_type
    return tuple(zone.position for zone in zones if zone.zone_type == zone_type)


def active_task_record(state) -> TaskState | None:
    """尽力解析当前活跃任务对应的 ``TaskState``。

    官方协议没有单独返回 accepted-task id，因此这里根据当前 TaskPoint 锚点与
    ``playerTasks.taskPosition`` 做匹配。用于 timeout/奖励等策略信息，不参与协议安全判定。
    """
    anchors = active_task_anchor_positions(state)
    if not anchors:
        return None
    anchor_set = {(p.x, p.y) for p in anchors}
    for task in state.tasks:
        if task.position is None:
            continue
        cells = task_zone_positions_for_task(state, task)
        if any((p.x, p.y) in anchor_set for p in cells):
            return task
    return None
