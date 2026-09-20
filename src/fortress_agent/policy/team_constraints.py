from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass

from fortress_agent.domain.action import (
    AttackAction,
    BuildAction,
    MoveAction,
    ExploreAction,
    BuyAction,
    DropAction,
    SellAction,
    SummonTreasureAction,
    UseAction,
)
from fortress_agent.domain.decision import Decision
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.construction_priority import opening_construction_priority
from fortress_agent.game_rules.catalog import WEAPON_TYPES, building_rule
from fortress_agent.game_rules.economy import next_weapon_build_type


@dataclass(frozen=True, slots=True)
class TeamConstraintResult:
    decisions: tuple[Decision, ...]
    dropped_decision_ids: tuple[str, ...] = ()


class TeamConstraint(ABC):
    """联合动作冲突约束抽象类。

    本文件后半部分提供具体实现，包括 UniqueActor、WeaponController、GoldBudget、
    InventoryConsumption、UniqueBuildTarget、Weapon/WallBuildLimit、
    JointMoveCollision。新增团队级规则优先实现为 TeamConstraint，而不是塞进
    TeamPlanner 的 if/else。
    """

    constraint_id: str
    priority: int = 100

    @abstractmethod
    def apply(
        self,
        ctx: PolicyContext | None,
        decisions: tuple[Decision, ...],
    ) -> TeamConstraintResult:
        ...


class TeamConstraintRegistry:
    def __init__(self) -> None:
        self._constraints: dict[str, TeamConstraint] = {}

    def register(
        self,
        constraint: TeamConstraint,
    ) -> None:
        if constraint.constraint_id in self._constraints:
            raise ValueError(
                f"duplicate team constraint: {constraint.constraint_id}"
            )
        self._constraints[constraint.constraint_id] = constraint

    def apply(
        self,
        ctx: PolicyContext | None,
        decisions: tuple[Decision, ...],
    ) -> TeamConstraintResult:
        current = tuple(decisions)
        dropped: list[str] = []

        ordered = sorted(
            self._constraints.values(),
            key=lambda item: (
                item.priority,
                item.constraint_id,
            ),
        )

        for constraint in ordered:
            result = constraint.apply(
                ctx,
                current,
            )
            current = result.decisions
            dropped.extend(
                result.dropped_decision_ids
            )

        return TeamConstraintResult(
            decisions=current,
            dropped_decision_ids=tuple(dropped),
        )


def decision_key(decision: Decision) -> str:
    return (
        f"{decision.policy_version}:"
        f"{decision.strategy_id}:"
        f"{decision.action.actor_id}:"
        f"{decision.action.action_type}"
    )


def rank_key(decision: Decision):
    return (
        -decision.utility.total,
        decision.utility.risk,
        repr(decision.action),
    )


class UniqueActorConstraint(TeamConstraint):
    constraint_id = "unique_actor"
    priority = 10

    def apply(self, ctx, decisions):
        by_actor: dict[str, Decision] = {}
        dropped: list[str] = []

        for decision in decisions:
            key = str(decision.action.actor_id)
            old = by_actor.get(key)

            if old is None:
                by_actor[key] = decision
                continue

            winner, loser = sorted(
                (old, decision),
                key=rank_key,
            )
            by_actor[key] = winner
            dropped.append(
                decision_key(loser)
            )

        return TeamConstraintResult(
            tuple(by_actor.values()),
            tuple(dropped),
        )


class WeaponControllerConstraint(TeamConstraint):
    constraint_id = "weapon_controller"
    priority = 20

    def apply(self, ctx, decisions):
        selected = list(decisions)
        dropped: list[str] = []

        grouped: dict[str, list[Decision]] = {}

        for decision in selected:
            if isinstance(
                decision.action,
                AttackAction,
            ):
                grouped.setdefault(
                    str(
                        decision.action.controller_id
                    ),
                    [],
                ).append(decision)

        for controller, attacks in grouped.items():
            if len(attacks) > 1:
                ordered = sorted(
                    attacks,
                    key=rank_key,
                )
                for loser in ordered[1:]:
                    if loser in selected:
                        selected.remove(loser)
                        dropped.append(
                            decision_key(loser)
                        )

        # Conservative rule: the controller's turn is occupied while operating
        # a weapon. Compare its own direct action with the chosen attack.
        for attack in tuple(selected):
            if not isinstance(
                attack.action,
                AttackAction,
            ):
                continue

            controller_id = str(
                attack.action.controller_id
            )
            own = next(
                (
                    decision
                    for decision in selected
                    if (
                        decision is not attack
                        and str(
                            decision.action.actor_id
                        ) == controller_id
                    )
                ),
                None,
            )

            if own is None:
                continue

            winner, loser = sorted(
                (attack, own),
                key=rank_key,
            )

            if loser in selected:
                selected.remove(loser)
                dropped.append(
                    decision_key(loser)
                )

        return TeamConstraintResult(
            tuple(selected),
            tuple(dropped),
        )


class GoldBudgetConstraint(TeamConstraint):
    constraint_id = "gold_budget"
    priority = 40

    def apply(self, ctx, decisions):
        if ctx is None:
            return TeamConstraintResult(decisions)

        buys = [
            decision
            for decision in decisions
            if isinstance(
                decision.action,
                BuyAction,
            )
        ]

        weapon_builds = [
            decision for decision in decisions
            if isinstance(decision.action, BuildAction)
            and decision.action.name.lower() in WEAPON_TYPES
        ]

        if not buys and not weapon_builds:
            return TeamConstraintResult(decisions)

        # Do not count same-round sells as spendable gold; action ordering is
        # undocumented. Allocate only gold already present in GameState.
        budget = float(ctx.state.gold_self)
        # Keep one tower's gold while the builder travels to a legal build cell.
        if any(opening_construction_priority(ctx.state, d.action) == 1 for d in decisions):
            rule = building_rule(next_weapon_build_type(ctx.state))
            if rule is not None:
                budget = max(0.0, budget - rule.build_gold_cost)

        spenders = [*buys, *weapon_builds]
        selected = [decision for decision in decisions if decision not in spenders]
        dropped: list[str] = []

        for decision in sorted(spenders, key=lambda d: (
            -opening_construction_priority(ctx.state, d.action), rank_key(d),
        )):
            action = decision.action
            if isinstance(action, BuildAction):
                rule = building_rule(action.name)
                cost = float(rule.build_gold_cost if rule is not None else 0)
            else:
                price = ctx.state.weapon_shop.get(action.name)
                if price is None:
                    price = next((v for k, v in ctx.state.weapon_shop.items() if k.lower() == action.name.lower()), None)
                if price is None:
                    dropped.append(decision_key(decision))
                    continue
                cost = float(price) * action.num

            if cost <= budget:
                selected.append(decision)
                budget -= cost
            else:
                dropped.append(
                    decision_key(decision)
                )

        return TeamConstraintResult(
            tuple(selected),
            tuple(dropped),
        )


class InventoryConsumptionConstraint(TeamConstraint):
    constraint_id = "inventory_consumption"
    priority = 50

    def apply(self, ctx, decisions):
        if ctx is None:
            return TeamConstraintResult(decisions)

        inventory_by_actor = {
            str(actor.actor_id): Counter({
                item.item_type.lower(): item.amount
                for item in actor.inventory
            })
            for actor in ctx.state.characters
        }

        selected: list[Decision] = []
        dropped: list[str] = []
        remaining = {
            actor_id: counter.copy()
            for actor_id, counter
            in inventory_by_actor.items()
        }

        for decision in sorted(
            decisions,
            key=rank_key,
        ):
            actor_id = str(
                decision.action.actor_id
            )
            cost = self._item_cost(
                decision
            )

            if not cost:
                selected.append(decision)
                continue

            available = remaining.get(
                actor_id,
                Counter(),
            )

            if any(
                available[item] < amount
                for item, amount in cost.items()
            ):
                dropped.append(
                    decision_key(decision)
                )
                continue

            available.subtract(cost)
            selected.append(decision)

        return TeamConstraintResult(
            tuple(selected),
            tuple(dropped),
        )

    @staticmethod
    def _item_cost(
        decision: Decision,
    ) -> Counter[str]:
        action = decision.action

        if isinstance(action, SellAction):
            return Counter({
                action.name.lower(): action.num
            })

        if isinstance(action, DropAction):
            return Counter({
                action.name.lower(): 1
            })

        if isinstance(action, UseAction):
            return Counter({
                action.name.lower(): 1
            })

        if isinstance(action, SummonTreasureAction):
            return Counter(item.lower() for item in action.items)

        if isinstance(action, BuildAction):
            rule = building_rule(action.name)
            if rule is not None:
                return Counter({item.lower(): amount for item, amount in rule.build_items})

        return Counter()


class UniqueBuildTargetConstraint(TeamConstraint):
    constraint_id = "unique_build_target"
    priority = 60

    def apply(self, ctx, decisions):
        by_target: dict[
            tuple[int, int],
            Decision,
        ] = {}
        selected: list[Decision] = []
        dropped: list[str] = []

        for decision in sorted(
            decisions,
            key=rank_key,
        ):
            if not isinstance(
                decision.action,
                BuildAction,
            ):
                selected.append(decision)
                continue

            target = (
                decision.action.target.x,
                decision.action.target.y,
            )

            if target in by_target:
                dropped.append(
                    decision_key(decision)
                )
                continue

            by_target[target] = decision
            selected.append(decision)

        return TeamConstraintResult(
            tuple(selected),
            tuple(dropped),
        )


class WeaponBuildLimitConstraint(TeamConstraint):
    constraint_id = "weapon_build_limit"
    priority = 70
    WEAPONS = set(WEAPON_TYPES)

    def apply(self, ctx, decisions):
        if ctx is None:
            return TeamConstraintResult(decisions)
        existing_weapons = [
            b for b in ctx.state.buildings
            if b.owner == "self" and b.building_type in self.WEAPONS
        ]
        weapon_positions = {(b.position.x, b.position.y) for b in existing_weapons}
        remaining_new_slots = max(0, 3 - len(existing_weapons))
        selected = []
        dropped = []
        new_weapon_builds = 0
        for decision in sorted(decisions, key=rank_key):
            action = decision.action
            if not isinstance(action, BuildAction) or action.name.lower() not in self.WEAPONS:
                selected.append(decision)
                continue
            replacing = (action.target.x, action.target.y) in weapon_positions
            if replacing or new_weapon_builds < remaining_new_slots:
                selected.append(decision)
                if not replacing:
                    new_weapon_builds += 1
            else:
                dropped.append(decision_key(decision))
        return TeamConstraintResult(tuple(selected), tuple(dropped))


class WallBuildLimitConstraint(TeamConstraint):
    constraint_id = "wall_build_limit"
    priority = 71

    def apply(self, ctx, decisions):
        if ctx is None:
            return TeamConstraintResult(decisions)
        remaining = max(0, 20 - sum(1 for b in ctx.state.buildings if b.owner == "self" and b.building_type == "wall"))
        selected = []
        dropped = []
        used = 0
        for decision in sorted(decisions, key=rank_key):
            if isinstance(decision.action, BuildAction) and decision.action.name.lower() == "wall":
                if used >= remaining:
                    dropped.append(decision_key(decision))
                    continue
                used += 1
            selected.append(decision)
        return TeamConstraintResult(tuple(selected), tuple(dropped))


class JointMoveCollisionConstraint(TeamConstraint):
    constraint_id = "joint_move_collision"
    priority = 15

    def apply(self, ctx, decisions):
        if ctx is None:
            return TeamConstraintResult(decisions)
        moves = [d for d in decisions if isinstance(d.action, (MoveAction, ExploreAction))]
        by_target = {}
        for d in moves:
            by_target.setdefault((d.action.x, d.action.y), []).append(d)
        drop_ids = set()
        # If two own roles want the same target, keep only the higher-ranked one.
        for group in by_target.values():
            if len(group) > 1:
                ordered = sorted(group, key=rank_key)
                for loser in ordered[1:]:
                    drop_ids.add(id(loser))
        starts = {str(a.actor_id): (a.position.x, a.position.y) for a in ctx.state.characters}
        move_by_actor = {str(d.action.actor_id): d for d in moves}
        for aid, a in move_by_actor.items():
            for bid, b in move_by_actor.items():
                if aid >= bid:
                    continue
                if (a.action.x, a.action.y) == starts.get(bid) and (b.action.x, b.action.y) == starts.get(aid):
                    # Swap always collides; keep neither because choosing one
                    # still targets the other's occupied starting cell.
                    drop_ids.update({id(a), id(b)})
        selected = [d for d in decisions if id(d) not in drop_ids]
        dropped = [decision_key(d) for d in decisions if id(d) in drop_ids]
        return TeamConstraintResult(tuple(selected), tuple(dropped))


def build_default_team_constraints():
    registry = TeamConstraintRegistry()
    registry.register(UniqueActorConstraint())
    registry.register(JointMoveCollisionConstraint())
    registry.register(WeaponControllerConstraint())
    registry.register(
        GoldBudgetConstraint()
    )
    registry.register(
        InventoryConsumptionConstraint()
    )
    registry.register(
        UniqueBuildTargetConstraint()
    )
    registry.register(WeaponBuildLimitConstraint())
    registry.register(WallBuildLimitConstraint())
    return registry
