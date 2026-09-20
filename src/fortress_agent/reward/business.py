from __future__ import annotations

from fortress_agent.domain.action import (
    AcceptTaskAction,
    BuildAction,
    BuyAction,
    RemoveAction,
    SellAction,
    SubmitAnswerAction,
    SummonTreasureAction,
    UseAction,
)
from fortress_agent.domain.reward import RewardBreakdown
from fortress_agent.policy.build_catalog import BuildCatalog
from fortress_agent.game_rules.catalog import DEFAULT_FIRST_WEAPON_TYPE, WEAPON_TYPES
from fortress_agent.game_rules.geometry import is_adjacent8
from fortress_agent.game_rules.build_area import wall_build_priority, weapon_build_priority
from fortress_agent.game_rules.economy import wall_construction_due, wall_return_urgent
from fortress_agent.game_rules.economy import wall_health_ratio
from fortress_agent.game_rules.upgrades import next_upgrade_target

from .base import ExpectedRewardModel


def _actor(ctx, actor_id):
    return next(
        (
            actor
            for actor in ctx.state.characters
            if actor.actor_id == actor_id
        ),
        None,
    )


class SellRewardModel(ExpectedRewardModel):
    model_id = "sell"

    def supports(self, action):
        return type(action) is SellAction

    def estimate(self, ctx, action):
        price = ctx.state.market_prices.get(
            action.name.lower(),
            0.0,
        )
        proceeds = float(price) * action.num

        # Selling conserves approximate economic value; reward only the
        # liquidity/flexibility gain so it does not dominate gathering.
        economy = proceeds * 0.20
        action_cost = 0.05

        return RewardBreakdown(
            economy=economy,
            action_cost=action_cost,
            total=economy - action_cost,
        )


class RemoveRewardModel(ExpectedRewardModel):
    model_id = "remove_wall"

    def supports(self, action):
        return type(action) is RemoveAction

    def estimate(self, ctx, action):
        wall = next((
            b for b in ctx.state.buildings
            if b.owner == "self" and b.building_type == "wall"
            and b.position == action.target
        ), None)
        if wall is None:
            return RewardBreakdown(risk=1000.0, total=-1000.0)
        missing = 1.0 - wall_health_ratio(wall)
        survival = 7.0 + 8.0 * missing
        action_cost = 0.10
        return RewardBreakdown(
            survival=survival,
            action_cost=action_cost,
            total=survival - action_cost,
        )


class BuyRewardModel(ExpectedRewardModel):
    model_id = "buy"

    def supports(self, action):
        return type(action) is BuyAction

    def estimate(self, ctx, action):
        price = float(
            ctx.state.weapon_shop.get(
                action.name,
                0.0,
            )
        ) * action.num

        actor = _actor(ctx, action.actor_id)
        survival = 0.0

        if (
            action.name == "Medicine"
            and actor is not None
            and actor.max_hp
        ):
            missing_ratio = max(
                0.0,
                (actor.max_hp - actor.hp)
                / actor.max_hp,
            )
            survival = price * (
                0.8 + missing_ratio
            )

        elif action.name == "WallFixer":
            damaged_values = [
                (
                    building.max_hp
                    - (building.hp or 0)
                )
                / building.max_hp
                for building in ctx.state.buildings
                if (
                    building.owner == "self"
                    and building.building_type == "wall"
                    and building.max_hp
                )
            ]
            damaged_ratio = max(
                damaged_values,
                default=0.0,
            )
            survival = price * (
                0.6 + damaged_ratio
            )

        # UpgradePlanner 暴露的是唯一下一目标。购买正确升级券不是普通消费，
        # 而是“矿石 -> 金币 -> 永久防御能力”的事务中间步骤。给出足以覆盖
        # 购买成本的战略收益，避免候选生成正确却被普通 MOVE 挤掉。
        upgrade = next_upgrade_target(ctx.state)
        if upgrade is not None and action.name == upgrade.voucher_name:
            stage_bonus = {
                "weapons_to_2": 28.0,
                "station_to_2": 22.0,
                "weapons_to_3": 32.0,
                "station_to_3": 25.0,
                "front_walls_to_2": 18.0,
                "other_walls_to_2": 14.0,
                "front_walls_to_3": 20.0,
                "other_walls_to_3": 16.0,
            }.get(upgrade.stage, 16.0)
            survival = max(survival, price + stage_bonus)

        economy = -price
        action_cost = 0.05
        total = (
            survival
            + economy
            - action_cost
        )

        return RewardBreakdown(
            survival=survival,
            economy=economy,
            action_cost=action_cost,
            total=total,
        )


class UseRewardModel(ExpectedRewardModel):
    model_id = "use"

    def supports(self, action):
        return type(action) is UseAction

    def estimate(self, ctx, action):
        actor = _actor(ctx, action.actor_id)

        if actor is None:
            return RewardBreakdown(
                risk=1000.0,
                total=-1000.0,
            )

        survival = 0.0

        if (
            action.name == "Medicine"
            and actor.max_hp
        ):
            missing_ratio = max(
                0.0,
                (actor.max_hp - actor.hp)
                / actor.max_hp,
            )
            survival = 20.0 * missing_ratio

        elif (
            action.name == "WallFixer"
            and action.target is not None
        ):
            wall = next(
                (
                    building
                    for building in ctx.state.buildings
                    if (
                        building.owner == "self"
                        and building.building_type == "wall"
                        and building.position
                        == action.target
                    )
                ),
                None,
            )
            if (
                wall is not None
                and wall.max_hp
                and wall.hp is not None
            ):
                missing_ratio = (
                    wall.max_hp - wall.hp
                ) / wall.max_hp
                survival = 15.0 * max(
                    0.0,
                    missing_ratio,
                )

        upgrade = next_upgrade_target(ctx.state)
        if (
            upgrade is not None
            and action.name == upgrade.voucher_name
            and action.target == upgrade.position
        ):
            survival = max(survival, {
                "weapons_to_2": 26.0,
                "station_to_2": 20.0,
                "weapons_to_3": 30.0,
                "station_to_3": 23.0,
                "front_walls_to_2": 17.0,
                "other_walls_to_2": 13.0,
                "front_walls_to_3": 19.0,
                "other_walls_to_3": 15.0,
            }.get(upgrade.stage, 15.0))

        action_cost = 0.05

        return RewardBreakdown(
            survival=survival,
            action_cost=action_cost,
            total=survival - action_cost,
        )


class AcceptTaskRewardModel(ExpectedRewardModel):
    model_id = "accept_task"

    def __init__(
        self,
        *,
        default_success_probability: float = 0.5,
        gold_value_weight: float = 0.20,
    ) -> None:
        self._p = default_success_probability
        self._gold_weight = gold_value_weight

    def supports(self, action):
        return type(action) is AcceptTaskAction

    def estimate(self, ctx, action):
        actor = _actor(ctx, action.actor_id)

        if actor is None:
            return RewardBreakdown(
                risk=1000.0,
                total=-1000.0,
            )

        task = next(
            (
                task
                for task in ctx.state.tasks
                if (
                    task.status == "available"
                    and task.position is not None
                    and is_adjacent8(task.position, actor.position)
                )
            ),
            None,
        )

        if task is None:
            return RewardBreakdown(
                risk=1000.0,
                total=-1000.0,
            )

        gold_reward = float(
            task.payload.get(
                "gold_reward",
                0,
            )
        )

        gross = (
            float(task.reward or 0.0)
            + gold_reward
            * self._gold_weight
        )

        task_value = gross * self._p

        timeout = task.timeout_rounds or 1
        time_cost = min(
            2.0,
            10.0 / max(1, timeout),
        )

        total = task_value - time_cost

        return RewardBreakdown(
            task=task_value,
            action_cost=time_cost,
            total=total,
        )


class SubmitAnswerRewardModel(ExpectedRewardModel):
    model_id = "submit_answer"

    def supports(self, action):
        return type(action) is SubmitAnswerAction

    def estimate(self, ctx, action):
        # The answer provider is responsible for confidence. Keep the model
        # conservative until task scoring details are learned from outcomes.
        value = 1.0 if action.task_answer.strip() else 0.0
        return RewardBreakdown(
            task=value,
            action_cost=0.1,
            total=value - 0.1,
        )


class TreasureRewardModel(ExpectedRewardModel):
    model_id = "summon_treasure"

    def supports(self, action):
        return type(action) is SummonTreasureAction

    def estimate(self, ctx, action):
        # Summoning always consumes legal sacrifice items, even when no
        # treasure opens. Candidate generation is therefore provider-gated.
        information = 1.0
        risk = 1.0
        return RewardBreakdown(
            information=information,
            risk=risk,
            action_cost=0.2,
            total=-0.2,
        )


class BuildRewardModel(ExpectedRewardModel):
    model_id = "build"

    def __init__(
        self,
        catalog: BuildCatalog | None = None,
    ) -> None:
        self._catalog = catalog or BuildCatalog.official_default()

    def supports(self, action):
        return type(action) is BuildAction

    def estimate(self, ctx, action):
        recipe = self._catalog.get(
            action.name
        )
        if recipe is None:
            return RewardBreakdown(
                risk=1000.0,
                total=-1000.0,
            )

        survival = recipe.strategic_value
        existing_weapon_count = sum(
            1
            for building in ctx.state.buildings
            if building.owner == "self" and building.building_type in WEAPON_TYPES
        )
        workers = sorted(
            (actor for actor in ctx.state.characters if actor.role == "worker"),
            key=lambda actor: str(actor.actor_id),
        )
        primary_builder_id = str(workers[0].actor_id) if workers else ""

        action_cost = (sum(recipe.required_items.values()) * 0.25) + (recipe.gold_cost * 0.05)

        # 开局固定分工：最低 ID Worker 是主建设者；第一座武器优先 Rocket。
        # 第二 Worker 保留给采矿，避免两名 Worker 一起追逐 build utility。
        if action.name.lower() in WEAPON_TYPES and existing_weapon_count < 3:
            if action.name.lower() == DEFAULT_FIRST_WEAPON_TYPE:
                survival += 3.0
            survival += 1.5 * weapon_build_priority(ctx.state, action.target)
            if str(action.actor_id) == primary_builder_id:
                survival += 3.0
            else:
                action_cost += 3.5

        # 三座武器成形后，石头应转化为外层围墙，而不是长期留在背包。
        if action.name.lower() == "wall" and existing_weapon_count >= 3:
            survival += 3.0 + 2.5 * wall_build_priority(ctx.state, action.target)
            if wall_construction_due(ctx.state, ctx.policy_state):
                survival += 4.0
            if wall_return_urgent(ctx.state, ctx.policy_state):
                survival += 3.0

        return RewardBreakdown(
            survival=survival,
            action_cost=action_cost,
            total=survival - action_cost,
        )
