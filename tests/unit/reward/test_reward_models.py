from types import MappingProxyType

from fortress_agent.domain.action import AcceptTaskAction, BuildAction, ExploreAction, GatherAction
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.domain.state import Position
from fortress_agent.memory.world import WorldMemory
from fortress_agent.policy.context import PolicyContext
from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.reward.models import (
    ExplorationRewardModel,
    GatherRewardModel,
)
from fortress_agent.reward.business import AcceptTaskRewardModel, BuildRewardModel


class Deadline:
    def remaining(self):
        return 10.0
    def expired(self):
        return False


def parse(payload):
    result = GameProtocolCodec().parse_state(payload)
    assert result.ok, result
    return result.value


def test_exploration_reward_values_unknown_cell_more_than_known_cell():
    state = parse({
        "round": 10,
        "day": 1,
        "phase": "day",
        "characters": [{
            "id": 1,
            "role": "pioneer",
            "hp": 200,
            "position": {"x": 1, "y": 1},
        }],
    })

    memory = WorldMemory()
    memory.map.observe(
        x=2,
        y=1,
        round_id=10,
        terrain="road",
    )

    ctx = PolicyContext(
        state=state,
        world_memory=memory.view(),
        policy_state=PolicyState(),
        deadline=Deadline(),
        features=MappingProxyType({"combat.base_risk": 0.0}),
    )

    model = ExplorationRewardModel()

    known = model.estimate(
        ctx,
        ExploreAction(
            actor_id=1,
            action_type="move",
            x=2,
            y=1,
        ),
    )
    unknown = model.estimate(
        ctx,
        ExploreAction(
            actor_id=1,
            action_type="move",
            x=1,
            y=2,
        ),
    )

    assert unknown.total > known.total
    assert unknown.information > known.information


def test_gather_reward_uses_market_price_and_backpack_capacity():
    state = parse({
        "round": 1,
        "day": 1,
        "phase": "day",
        "characters": [{
            "id": 1,
            "role": "worker",
            "hp": 220,
            "position": {"x": 5, "y": 5},
            "backpack_capacity": 100,
            "inventory": {"stone": 95},
        }],
        "prices": {"iron": 3.0},
    })

    memory = WorldMemory()
    memory.resources.discover(
        resource_id="iron-1",
        resource_type="iron",
        x=5,
        y=5,
        amount=100,
        round_id=1,
    )

    ctx = PolicyContext(
        state=state,
        world_memory=memory.view(),
        policy_state=PolicyState(),
        deadline=Deadline(),
        features=MappingProxyType({}),
    )

    reward = GatherRewardModel(
        default_gather_units=10
    ).estimate(
        ctx,
        GatherAction(
            actor_id=1,
            action_type="gather",
            resource_id="iron-1",
        ),
    )

    # Only 5 backpack slots remain; market price is 3.
    assert reward.economy == 15.0
    assert reward.total > 14.0


def test_first_weapon_default_strategy_prefers_rocket():
    state = parse({
        "round": 10,
        "day": 1,
        "phase": "day",
        "gold_self": 75,
        "characters": [{
            "id": 1,
            "role": "worker",
            "hp": 220,
            "position": {"x": 9, "y": 10},
        }],
        "buildings": [{
            "id": 10013,
            "type": "station",
            "owner": "self",
            "hp": 1500,
            "position": {"x": 10, "y": 10},
            "footprint_width": 2,
            "footprint_height": 2,
            "footprint_anchor": "top_left",
        }],
    })
    ctx = PolicyContext(
        state=state,
        world_memory=WorldMemory().view(),
        policy_state=PolicyState(),
        deadline=Deadline(),
        features=MappingProxyType({}),
    )
    model = BuildRewardModel()

    rocket = model.estimate(ctx, BuildAction(
        actor_id=1, action_type="build", name="rocket", target=Position(9, 10)
    ))
    railgun = model.estimate(ctx, BuildAction(
        actor_id=1, action_type="build", name="railgun", target=Position(9, 10)
    ))
    gatling = model.estimate(ctx, BuildAction(
        actor_id=1, action_type="build", name="gatling", target=Position(9, 10)
    ))

    assert rocket.total > railgun.total > gatling.total


def test_accept_task_reward_supports_second_cell_of_task_point_2():
    state = parse({
        "roundNo": 10,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": [
                {"neutralType": "challengerTaskPoint2", "pos": {"x": 10, "y": 10}},
                {"neutralType": "challengerTaskPoint2", "pos": {"x": 10, "y": 11}},
            ],
        },
        "teamOur": {
            "type": "challenger",
            "goldNum": 0,
            "totalScore": 0,
            "playerTasks": [{
                "taskType": "自进化类2",
                "taskPosition": {"x": 10, "y": 10},
                "coldDownRounds": 0,
                "scoreReward": 50,
                "goldReward": 30,
                "isValid": True,
                "timeoutRounds": 20,
            }],
            # Adjacent to the second physical cell, but not taskPosition.
            "roles": [{
                "id": 11,
                "pos": {"x": 9, "y": 12},
                "roleType": "pioneer",
                "health": 200,
                "backPackCapability": 40,
                "backpack": [],
            }],
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": []},
        "errors": [],
    })
    ctx = PolicyContext(
        state=state,
        world_memory=WorldMemory().view(),
        policy_state=PolicyState(),
        deadline=Deadline(),
        features=MappingProxyType({}),
    )

    reward = AcceptTaskRewardModel().estimate(
        ctx,
        AcceptTaskAction(actor_id=11, action_type="acceptTask"),
    )

    assert reward.risk == 0.0
    assert reward.total > 0.0
