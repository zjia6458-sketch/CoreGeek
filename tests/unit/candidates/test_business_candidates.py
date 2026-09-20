from types import MappingProxyType

from fortress_agent.candidates.business import (
    AcceptTaskCandidateGenerator,
    BuildCandidateGenerator,
    BuyCandidateGenerator,
    SellCandidateGenerator,
    UseCandidateGenerator,
)
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.memory.world import WorldMemory
from fortress_agent.game_rules.build_area import VerifiedBuildAreaPolicy
from fortress_agent.policy.build_catalog import (
    BuildCatalog,
    BuildRecipe,
)
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.strategy import StrategyProfile
from fortress_agent.protocol.codec import GameProtocolCodec


class Deadline:
    def remaining(self):
        return 10.0

    def expired(self):
        return False


def state():
    result = GameProtocolCodec().parse_state({
        "roundNo": 10,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": [
                {
                    "neutralType": "vendor",
                    "pos": {"x": 5, "y": 5},
                },
                {
                    "neutralType": "weaponShop",
                    "pos": {"x": 6, "y": 6},
                },
                {
                    "neutralType": "challengerTaskPoint1",
                    "pos": {"x": 7, "y": 7},
                },
            ],
        },
        "teamOur": {
            "type": "challenger",
            "teamId": "x",
            "teamName": "x",
            "goldNum": 30,
            "totalScore": 0,
            "playerTasks": [{
                "taskType": "自进化类1",
                "taskPosition": {"x": 7, "y": 7},
                "coldDownRounds": 0,
                "scoreReward": 50,
                "goldReward": 30,
                "isValid": True,
                "timeoutRounds": 20,
            }],
            "roles": [
                {
                    "id": 10010,
                    "pos": {"x": 5, "y": 4},
                    "roleType": "worker",
                    "health": 200,
                    "attackPower": 0,
                    "attackRange": 0,
                    "backPackCapability": 100,
                    "backpack": ["stone", "Medicine"],
                },
                {
                    "id": 10012,
                    "pos": {"x": 6, "y": 5},
                    "roleType": "worker",
                    "health": 180,
                    "attackPower": 0,
                    "attackRange": 0,
                    "backPackCapability": 100,
                    "backpack": [],
                },
                {
                    "id": 10011,
                    "pos": {"x": 7, "y": 6},
                    "roleType": "pioneer",
                    "health": 200,
                    "attackPower": 0,
                    "attackRange": 0,
                    "backPackCapability": 40,
                    "backpack": [],
                },
            ],
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": []},
        "vendorShopList": [
            {"name": "stone", "price": 1},
        ],
        "weaponShopList": [
            {"name": "Medicine", "price": 10},
            {"name": "WallFixer", "price": 10},
        ],
        "errors": [],
    })
    assert result.ok, result
    return result.value


def ctx():
    return PolicyContext(
        state=state(),
        world_memory=WorldMemory().view(),
        policy_state=PolicyState.create(),
        deadline=Deadline(),
        features=MappingProxyType({}),
    )


def profile(*tags):
    return StrategyProfile(
        strategy_id="test",
        candidate_tags=frozenset(tags),
    )


def test_sell_requires_conservative_vendor_locality():
    actions = SellCandidateGenerator().generate(
        ctx(),
        profile("sell"),
    )

    assert len(actions) == 1
    assert actions[0].actor_id == 10010
    assert actions[0].name == "stone"


def test_medicine_is_not_bought_for_actor_above_configured_low_hp_threshold():
    actions = BuyCandidateGenerator().generate(
        ctx(),
        profile("buy"),
    )
    assert not any(action.name == "Medicine" for action in actions)


def test_medicine_is_not_used_for_actor_above_configured_low_hp_threshold():
    actions = UseCandidateGenerator().generate(
        ctx(),
        profile("use"),
    )
    assert not any(action.name == "Medicine" for action in actions)


def test_accept_task_candidate_uses_real_task_state():
    actions = AcceptTaskCandidateGenerator().generate(
        ctx(),
        profile("task"),
    )

    assert len(actions) == 1
    assert actions[0].actor_id == 10011


def test_build_plugin_is_disabled_without_verified_build_area():
    actions = BuildCandidateGenerator().generate(
        ctx(),
        profile("build"),
    )

    assert actions == ()


def test_build_plugin_requires_recipe_and_verified_build_area():
    catalog = BuildCatalog((
        BuildRecipe(
            building_name="wall",
            required_items={"stone": 1},
            strategic_value=4.0,
        ),
    ))

    actions = BuildCandidateGenerator(
        catalog,
        VerifiedBuildAreaPolicy.from_config(wall_cells=((4, 4),)),
    ).generate(
        ctx(),
        profile("build"),
    )

    assert actions
    assert all(
        action.name == "wall"
        for action in actions
    )
