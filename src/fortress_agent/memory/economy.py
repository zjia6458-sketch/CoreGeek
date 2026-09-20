"""跨回合经济/采矿会话记忆。

记录当前 Worker 承诺的矿点、商人目标、承诺起始回合和夜前紧急额外采集。它不是长期世界
知识，不写磁盘；目标失效/危险时 Candidate 可以立即释放，避免 A/B 矿点震荡。
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from fortress_agent.domain.action import (
    GatherAction,
    GoalApproachAction,
    ResourceApproachAction,
    SellAction,
)


@dataclass(frozen=True, slots=True)
class MiningRuntimeMemoryView:
    committed_resource_by_actor: Mapping[str, str]
    committed_since_round_by_actor: Mapping[str, int]
    emergency_sample_by_actor: Mapping[str, tuple[int, str]]
    vendor_by_actor: Mapping[str, tuple[int, int]] = field(default_factory=lambda: MappingProxyType({}))

    def vendor_target(self, actor_id) -> tuple[int, int] | None:
        return self.vendor_by_actor.get(str(actor_id))

    def committed_resource(self, actor_id) -> str | None:
        return self.committed_resource_by_actor.get(str(actor_id))

    def commitment_age(self, actor_id, current_round: int) -> int | None:
        since = self.committed_since_round_by_actor.get(str(actor_id))
        if since is None:
            return None
        return max(0, int(current_round) - int(since))

    def commitment_active(self, actor_id, *, current_round: int, min_rounds: int) -> bool:
        resource = self.committed_resource(actor_id)
        age = self.commitment_age(actor_id, current_round)
        return resource is not None and age is not None and age < max(0, int(min_rounds))

    def emergency_sample_taken(self, actor_id, *, day: int, resource_id) -> bool:
        return self.emergency_sample_by_actor.get(str(actor_id)) == (int(day), str(resource_id))


class MiningRuntimeMemory:
    def __init__(self) -> None:
        self._committed: dict[str, tuple[str, int]] = {}
        self._emergency_sample: dict[str, tuple[int, str]] = {}
        self._vendors: dict[str, tuple[int, int]] = {}

    def view(self) -> MiningRuntimeMemoryView:
        return MiningRuntimeMemoryView(
            committed_resource_by_actor=MappingProxyType({
                actor: value[0] for actor, value in self._committed.items()
            }),
            committed_since_round_by_actor=MappingProxyType({
                actor: value[1] for actor, value in self._committed.items()
            }),
            emergency_sample_by_actor=MappingProxyType(dict(self._emergency_sample)),
            vendor_by_actor=MappingProxyType(dict(self._vendors)),
        )

    def reconcile(self, *, state, world_memory) -> None:
        from fortress_agent.game_rules.economy import sellable_amount

        vendors = {(z.position.x, z.position.y) for z in state.neutral_zones if z.zone_type == "vendor"}
        actors = {str(a.actor_id): a for a in state.characters if a.hp > 0}
        for actor_id, target in tuple(self._vendors.items()):
            actor = actors.get(actor_id)
            if actor is None or target not in vendors or not any(
                sellable_amount(state, actor, name) > 0 for name in state.market_prices
            ):
                self._vendors.pop(actor_id, None)
        available_ids = {str(r.resource_id) for r in world_memory.available_resources()}
        living_workers = {
            str(a.actor_id) for a in state.characters if a.role == "worker" and a.hp > 0
        }
        for actor_id in tuple(self._committed):
            resource_id, _ = self._committed[actor_id]
            if actor_id not in living_workers or resource_id not in available_ids:
                self._committed.pop(actor_id, None)
        for actor_id, (day, resource_id) in tuple(self._emergency_sample.items()):
            if actor_id not in living_workers or day != int(state.day) or resource_id not in available_ids:
                self._emergency_sample.pop(actor_id, None)

    def release(self, actor_id) -> None:
        self._committed.pop(str(actor_id), None)

    def record_confirmed_action(self, *, state, action, emergency_rounds: int) -> None:
        """记录服务器未明确判失败的上一回合动作。"""
        remaining = state.turns_until_phase_change
        in_emergency = (
            state.phase == "day"
            and remaining is not None
            and remaining <= max(0, int(emergency_rounds))
        )
        actor_id = str(action.actor_id)
        if isinstance(action, GoalApproachAction) and action.goal_kind == "vendor":
            self._vendors[actor_id] = (action.goal_x, action.goal_y)
            self.release(actor_id)
        elif isinstance(action, SellAction):
            self.release(actor_id)
            actor = next((a for a in state.characters if str(a.actor_id) == actor_id), None)
            if actor is not None:
                from fortress_agent.game_rules.geometry import is_adjacent8
                vendor = next((z for z in state.neutral_zones if z.zone_type == "vendor"
                               and is_adjacent8(actor.position, z.position)), None)
                if vendor is not None:
                    self._vendors[actor_id] = (vendor.position.x, vendor.position.y)
        if isinstance(action, ResourceApproachAction):
            rid = str(action.resource_id)
            previous = self._committed.get(actor_id)
            since = previous[1] if previous is not None and previous[0] == rid else int(state.round_id)
            self._committed[actor_id] = (rid, since)
        elif isinstance(action, GatherAction):
            rid = str(action.resource_id)
            previous = self._committed.get(actor_id)
            since = previous[1] if previous is not None and previous[0] == rid else int(state.round_id)
            self._committed[actor_id] = (rid, since)
            if in_emergency:
                self._emergency_sample[actor_id] = (int(state.day), rid)
