from __future__ import annotations

from fortress_agent.domain.action import (
    AttackAction,
    ExploreAction,
    GatherAction,
    MoveAction,
    ResourceApproachAction,
)
from fortress_agent.domain.reward import RewardBreakdown
from fortress_agent.domain.state import Position
from fortress_agent.game_rules.geometry import chebyshev_distance
from fortress_agent.game_rules.combat import estimate_attack_value
from fortress_agent.game_rules.economy import (
    wall_construction_due, wall_return_urgent, resource_selection_score,
)
from fortress_agent.policy.context import PolicyContext
from fortress_agent.world.threat import ThreatMapBuilder

from .base import ExpectedRewardModel


def _actor(ctx: PolicyContext, actor_id):
    return next(
        (
            actor
            for actor in ctx.state.characters
            if actor.actor_id == actor_id
        ),
        None,
    )


class MoveRewardModel(ExpectedRewardModel):
    model_id = "move"

    def __init__(
        self,
        threat_builder: ThreatMapBuilder | None = None,
    ) -> None:
        self._threat_builder = (
            threat_builder
            or ThreatMapBuilder()
        )

    def supports(self, action) -> bool:
        return type(action) is MoveAction

    def estimate(
        self,
        ctx: PolicyContext,
        action: MoveAction,
    ) -> RewardBreakdown:
        target = ctx.world_memory.cell(action.x, action.y)
        threat, _ = self._threat_builder.build(ctx.state)

        position = 0.0
        revisit_penalty = min(0.75, 0.08 * float(target.visit_count))
        action_cost = 0.10 + revisit_penalty
        risk = threat.value(action.x, action.y) * 0.02

        total = position - action_cost - risk

        return RewardBreakdown(
            position=position,
            action_cost=action_cost,
            risk=risk,
            total=total,
        )


class ResourceApproachRewardModel(ExpectedRewardModel):
    model_id = "resource_approach"

    def __init__(self, threat_builder: ThreatMapBuilder | None = None) -> None:
        self._threat_builder = threat_builder or ThreatMapBuilder()

    def supports(self, action) -> bool:
        return type(action) is ResourceApproachAction

    def estimate(self, ctx: PolicyContext, action: ResourceApproachAction) -> RewardBreakdown:
        resource = ctx.world_memory.resource(action.resource_id)
        actor = _actor(ctx, action.actor_id)
        if resource is None or actor is None:
            return RewardBreakdown(total=-1000.0, risk=1000.0)

        # 与 Candidate 预筛选使用同一套“距离优先、价值次之”公式，避免两层评分互相打架。
        source_distance = chebyshev_distance(actor.position, (resource.x, resource.y))
        selection_score, _, _ = resource_selection_score(
            ctx, actor, resource, distance=source_distance
        )
        remaining = chebyshev_distance((action.x, action.y), (resource.x, resource.y))
        economy = selection_score
        position = 0.75 if remaining == 1 else 0.25
        threat, _ = self._threat_builder.build(ctx.state)
        risk = threat.value(action.x, action.y) * 0.02
        action_cost = 0.10
        total = economy + position - risk - action_cost

        return RewardBreakdown(
            economy=economy,
            position=position,
            risk=risk,
            action_cost=action_cost,
            total=total,
        )


class ExplorationRewardModel(ExpectedRewardModel):
    model_id = "exploration"

    def __init__(
        self,
        threat_builder: ThreatMapBuilder | None = None,
    ) -> None:
        self._threat_builder = (
            threat_builder
            or ThreatMapBuilder()
        )

    def supports(self, action) -> bool:
        return type(action) is ExploreAction

    def estimate(
        self,
        ctx: PolicyContext,
        action: ExploreAction,
    ) -> RewardBreakdown:
        cell = ctx.world_memory.cell(action.x, action.y)
        threat, _ = self._threat_builder.build(ctx.state)

        information = 0.0

        if not cell.discovered:
            information += 3.0
        else:
            last_seen = cell.last_seen_round

            if last_seen is not None:
                age = max(
                    0,
                    ctx.state.round_id - last_seen,
                )
                information += min(
                    1.0,
                    age / 50.0,
                )

        frontier_set = set(
            ctx.world_memory.frontier_cells()
        )

        position = (
            0.75
            if (action.x, action.y) in frontier_set
            else 0.2
        )

        strategic_bonus = self._strategic_direction_bonus(
            ctx,
            action,
        )

        action_cost = 0.15
        risk = threat.value(action.x, action.y) * 0.03

        total = (
            information
            + position
            + strategic_bonus
            - action_cost
            - risk
        )

        return RewardBreakdown(
            information=information + strategic_bonus,
            position=position,
            action_cost=action_cost,
            risk=risk,
            total=total,
        )

    @staticmethod
    def _strategic_direction_bonus(
        ctx: PolicyContext,
        action: ExploreAction,
    ) -> float:
        if ctx.strategic_memory is None:
            return 0.0

        advisory = ctx.strategic_memory.active_advisory(
            ctx.state.round_id
        )
        if advisory is None:
            return 0.0

        actor = _actor(ctx, action.actor_id)
        if actor is None:
            return 0.0

        strength = advisory.effective_strength
        best = 0.0

        for objective in advisory.objectives:
            if objective.objective_type != "explore_region":
                continue

            region = objective.target_region
            aligned = (
                (region == "west" and action.x < actor.position.x)
                or (region == "east" and action.x > actor.position.x)
                or (region == "south" and action.y < actor.position.y)
                or (region == "north" and action.y > actor.position.y)
            )

            if aligned:
                best = max(
                    best,
                    objective.priority * strength,
                )

        return best


class GatherRewardModel(ExpectedRewardModel):
    model_id = "gather"

    def __init__(
        self,
        *,
        default_gather_units: int = 1,
        default_unit_value: float = 1.0,
    ) -> None:
        self._default_gather_units = (
            default_gather_units
        )
        self._default_unit_value = (
            default_unit_value
        )

    def supports(self, action) -> bool:
        return type(action) is GatherAction

    def estimate(
        self,
        ctx: PolicyContext,
        action: GatherAction,
    ) -> RewardBreakdown:
        resource = ctx.world_memory.resource(
            action.resource_id
        )
        actor = _actor(ctx, action.actor_id)

        if resource is None or actor is None:
            return RewardBreakdown(
                total=-1000.0,
                risk=1000.0,
            )

        amount = (
            self._default_gather_units
            if resource.last_known_amount is None
            else min(
                self._default_gather_units,
                max(
                    0,
                    resource.last_known_amount,
                ),
            )
        )

        if actor.backpack_capacity is not None:
            used = sum(
                item.amount
                for item in actor.inventory
            )
            remaining = max(
                0,
                actor.backpack_capacity - used,
            )
            amount = min(amount, remaining)

        unit_value = ctx.state.market_prices.get(
            resource.resource_type,
            self._default_unit_value,
        )

        economy = (
            float(amount)
            * float(unit_value)
        )
        weapon_count = sum(1 for b in ctx.state.buildings if b.owner == "self" and b.building_type in {"gatling","railgun","rocket"})
        wall_count = sum(1 for b in ctx.state.buildings if b.owner == "self" and b.building_type == "wall")
        if resource.resource_type.lower() == "stone" and weapon_count >= 3 and wall_count < 20:
            economy += 5.0 if wall_construction_due(ctx.state, ctx.policy_state) else 2.0
            if wall_return_urgent(ctx.state, ctx.policy_state):
                economy += 2.0
        # 当前矿黏性奖励参数化：只影响软 Utility，不改变合法性。
        if ctx.mining_memory is not None and ctx.mining_memory.committed_resource(actor.actor_id) == str(resource.resource_id):
            economy += float(ctx.policy_state.parameters.get("gather_current_mine_bonus", 2.5))
        action_cost = 0.05

        total = economy - action_cost

        return RewardBreakdown(
            economy=economy,
            action_cost=action_cost,
            total=total,
        )


class AttackRewardModel(ExpectedRewardModel):
    model_id = "attack"

    def supports(self, action) -> bool:
        return type(action) is AttackAction

    def estimate(self, ctx: PolicyContext, action: AttackAction) -> RewardBreakdown:
        weapon = next(
            (building for building in ctx.state.buildings if building.building_id == action.actor_id),
            None,
        )
        if weapon is None:
            return RewardBreakdown(risk=1000.0, total=-1000.0)

        score, survival = estimate_attack_value(ctx.state, weapon, action.targets)
        # 夜间合法攻击不应因为小目标分值过低而输给无意义移动。
        action_cost = 0.02
        total = score * 2.0 + survival - action_cost
        return RewardBreakdown(
            score=score * 2.0,
            survival=survival,
            action_cost=action_cost,
            total=total,
        )

