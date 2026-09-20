from __future__ import annotations

from fortress_agent.domain.action import GatherAction, MoveAction
from fortress_agent.domain.utility import UtilityBreakdown
from fortress_agent.game_rules.economy import vendor_trip_due
from fortress_agent.game_rules.geometry import is_adjacent8
from fortress_agent.game_rules.night_safety import (
    night_gather_is_safe,
    night_retreat_step,
)
from fortress_agent.memory.resources import ResourceStatus
from fortress_agent.policy.context import PolicyContext
from fortress_agent.world.traversability import TraversabilityMap


class EmergencyActionUnavailable(RuntimeError):
    """没有任何经过硬安全规则验证的 emergency action。"""


class BasicEmergencyPolicy:
    """确定性的紧急降级策略。

    实现位置：本类由 ``application/basic_policy.py`` 注入 PolicyGraph 的
    ``EmergencyNode``。当 Candidate 为空、Legal/Rule 拒绝全部动作，或者
    RuntimeModeResolver 判断剩余预算过低时使用。

    Emergency 仍复用正常 Traversability/FeedbackMemory，绝不会为了赶时间绕过
    资源格、TaskPoint、动态 terrain rule 等硬安全约束。
    """

    def select(self, ctx: PolicyContext):
        if ctx.state.phase.lower() == "night":
            for actor in sorted(ctx.state.characters, key=lambda a: str(a.actor_id)):
                if actor.hp <= 0 or actor.role != "worker":
                    continue
                step = night_retreat_step(ctx, actor)
                if step is not None:
                    return MoveAction(actor.actor_id, "move", step.x, step.y), UtilityBreakdown(total=12.0)
                if actor.backpack_capacity and sum(i.amount for i in actor.inventory) >= actor.backpack_capacity:
                    continue
                for resource in ctx.world_memory.available_resources():
                    if is_adjacent8(actor.position, (resource.x, resource.y)) and night_gather_is_safe(ctx, actor, resource):
                        return GatherAction(actor.actor_id, "gather", resource.resource_id), UtilityBreakdown(total=1.0)
            raise EmergencyActionUnavailable("no verified safe night action; hold position")

        traversability = TraversabilityMap.from_state_and_memory(
            ctx.state,
            ctx.world_memory,
            ctx.feedback_memory,
        )

        # 白天优先做一个确定合法的采集动作。正式规则允许 Worker 位于矿区
        # 8 邻域任一格进行 collect，因此使用 is_adjacent8 而不是旧 Manhattan。
        if ctx.state.phase.lower() == "day":
            for actor in sorted(
                ctx.state.characters,
                key=lambda x: str(x.actor_id),
            ):
                if actor.role.lower() != "worker":
                    continue
                if vendor_trip_due(ctx, actor):
                    continue
                for resource in ctx.world_memory.available_resources():
                    if resource.status is not ResourceStatus.AVAILABLE:
                        continue
                    if is_adjacent8(
                        actor.position,
                        (resource.x, resource.y),
                    ):
                        return (
                            GatherAction(
                                actor_id=actor.actor_id,
                                action_type="gather",
                                resource_id=resource.resource_id,
                            ),
                            UtilityBreakdown(total=0.0),
                        )

        # 没有可采集动作时，仅选择 Traversability 已确认可进入的相邻格。
        for actor in sorted(
            ctx.state.characters,
            key=lambda x: str(x.actor_id),
        ):
            if actor.hp <= 0 or (actor.role == "worker" and vendor_trip_due(ctx, actor)):
                continue
            for pos in traversability.walkable_neighbors(
                actor.position.x,
                actor.position.y,
            ):
                cell = ctx.world_memory.cell(pos.x, pos.y)
                if cell.terrain is not None and cell.terrain.lower() == "wall":
                    continue
                return (
                    MoveAction(
                        actor_id=actor.actor_id,
                        action_type="move",
                        x=pos.x,
                        y=pos.y,
                    ),
                    UtilityBreakdown(total=-1.0),
                )

        raise EmergencyActionUnavailable(
            "no verified traversable fallback action is available"
        )
