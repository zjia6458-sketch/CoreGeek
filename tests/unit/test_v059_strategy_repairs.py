from types import MappingProxyType

from fortress_agent.candidates.basic import GatherCandidateGenerator, ResourceApproachCandidateGenerator
from fortress_agent.candidates.business import BuildCandidateGenerator, RemoveCandidateGenerator
from fortress_agent.candidates.navigation import VendorApproachCandidateGenerator, WeaponShopApproachCandidateGenerator
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.domain.state import Position
from fortress_agent.game_rules.night_safety import night_gather_is_safe
from fortress_agent.game_rules.upgrades import next_upgrade_target
from fortress_agent.memory.movement import MovementHistoryMemory
from fortress_agent.memory.world import WorldMemory
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.strategy import StrategyProfile
from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.strategies.reference import build_reference_strategy_selector
from fortress_agent.world.pathfinding import AStarPathfinder
from fortress_agent.world.traversability import TraversabilityMap


class Deadline:
    def remaining(self):
        return 10.0

    def expired(self):
        return False


def role(role_id, x, y, role_type, *, health=None, backpack=None, level=1):
    return {
        "id": role_id,
        "pos": {"x": x, "y": y},
        "roleType": role_type,
        "health": health if health is not None else (220 if role_type == "worker" else 1000),
        "attackPower": 0,
        "attackRange": 10 if role_type == "rocket" else 0,
        "backPackCapability": 100 if role_type == "worker" else 0,
        "backpack": backpack or [],
        "level": level,
        "cooldown": 0,
    }


def state(*, round_no=10, roles, zones=(), gold=0, phase_task="", shop=(), vendor=()):
    result = GameProtocolCodec().parse_state({
        "roundNo": round_no,
        "mapInfo": {"width": 41, "height": 32, "zones": list(zones)},
        "teamOur": {
            "type": "challenger", "teamId": "x", "teamName": "x",
            "goldNum": gold, "totalScore": 0, "playerTasks": [], "roles": roles,
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": []},
        "phaseTask": phase_task,
        "lastCmdResult": "",
        "llmResp": "",
        "worldNews": {"officialNews": "", "folkLegends": ""},
        "vendorShopList": list(vendor),
        "weaponShopList": list(shop),
        "errors": [],
    })
    assert result.ok
    return result.value


def context(game_state, memory=None):
    return PolicyContext(
        state=game_state,
        world_memory=(memory or WorldMemory()).view(),
        policy_state=PolicyState.create(),
        deadline=Deadline(),
        features=MappingProxyType({}),
    )


def profile(*tags):
    return StrategyProfile(strategy_id="test", candidate_tags=frozenset(tags))


def test_diagonal_move_is_legal_between_two_orthogonal_blockers():
    # 1110
    # 0021  (2=current, upper-right 0 is a legal diagonal destination)
    traversability = TraversabilityMap(
        width=4,
        height=2,
        blocked=frozenset({(0, 0), (1, 0), (2, 0), (3, 1), (2, 1)}),
        resource_cells=frozenset(), task_cells=frozenset(), neutral_cells=frozenset(),
        building_cells=frozenset({(0, 0), (1, 0), (2, 0), (3, 1)}),
        character_cells=frozenset({(2, 1)}), robot_cells=frozenset(),
        learned_terrain_types=frozenset(), learned_terrain_cells=(),
    )
    result = AStarPathfinder(width=4, height=2).find_path(
        WorldMemory().view(), Position(2, 1), Position(3, 0),
        traversability=traversability,
    )
    assert result.found
    assert result.path == (Position(2, 1), Position(3, 0))


def test_safe_night_mining_is_not_limited_to_edge_resources():
    game = state(
        round_no=71,
        roles=[role(10, 19, 16, "worker")],
        zones=[{"neutralType": "iron", "pos": {"x": 20, "y": 16}}],
        vendor=[{"name": "iron", "price": 3}],
    )
    memory = WorldMemory()
    memory.resources.discover(
        resource_id="zone:iron:20:16", resource_type="iron",
        x=20, y=16, amount=10, round_id=71,
    )
    ctx = context(game, memory)
    actor = game.characters[0]
    resource = memory.view().available_resources()[0]
    assert night_gather_is_safe(ctx, actor, resource)


def test_critical_lowest_wall_is_removed_for_stone_rebuild():
    game = state(
        round_no=140,
        roles=[
            role(10, 8, 20, "worker", backpack=["stone"]),
            role(100, 9, 20, "wall", health=200),
            role(101, 8, 21, "wall", health=300),
        ],
    )
    actions = RemoveCandidateGenerator().generate(context(game), profile("build"))
    assert len(actions) == 1
    assert actions[0].target == Position(9, 20)


def test_weapon_plan_builds_gatling_after_first_rocket():
    game = state(
        roles=[
            role(10, 7, 21, "worker"),
            role(13, 9, 22, "station", health=1500),
            role(40, 8, 22, "rocket"),
        ],
        gold=50,
    )
    actions = BuildCandidateGenerator().generate(context(game), profile("build"))
    assert actions
    assert {action.name for action in actions} == {"gatling"}
    assert all(action.target != Position(8, 22) for action in actions)


def test_core_upgrades_start_before_all_walls_are_complete():
    game = state(
        roles=[
            role(13, 9, 22, "station", health=1500),
            role(40, 8, 22, "rocket"),
            role(41, 8, 21, "gatling"),
            role(42, 8, 20, "railgun"),
        ],
    )
    upgrade = next_upgrade_target(game)
    assert upgrade is not None
    assert upgrade.voucher_name == "WeaponUpgradeVoucher1"


def test_nonstone_batch_switches_from_mining_to_vendor():
    game = state(
        roles=[role(10, 10, 10, "worker", backpack=["iron"] * 4)],
        zones=[
            {"neutralType": "iron", "pos": {"x": 11, "y": 10}},
            {"neutralType": "vendor", "pos": {"x": 20, "y": 20}},
        ],
        vendor=[{"name": "iron", "price": 3}],
    )
    memory = WorldMemory()
    memory.resources.discover(
        resource_id="zone:iron:11:10", resource_type="iron",
        x=11, y=10, amount=10, round_id=10,
    )
    ctx = context(game, memory)
    assert GatherCandidateGenerator().generate(ctx, profile("gather")) == ()
    assert ResourceApproachCandidateGenerator().generate(ctx, profile("gather")) == ()
    assert VendorApproachCandidateGenerator().generate(ctx, profile("sell"))


def test_active_task_outranks_prepare_window():
    game = state(
        round_no=50,
        roles=[role(11, 13, 15, "pioneer", health=200)],
        phase_task="完成当前任务",
    )
    selected = build_reference_strategy_selector().select(context(game))
    assert selected.strategy_id == "active_task"


def test_unaffordable_upgrade_does_not_send_worker_toward_shop():
    game = state(
        roles=[
            role(10, 20, 20, "worker"),
            role(13, 9, 22, "station", health=1500),
            role(40, 8, 22, "rocket"),
            role(41, 8, 21, "gatling"),
            role(42, 8, 20, "railgun"),
        ],
        zones=[{"neutralType": "weaponShop", "pos": {"x": 5, "y": 5}}],
        gold=1,
        shop=[{"name": "WeaponUpgradeVoucher1", "price": 100}],
    )
    assert WeaponShopApproachCandidateGenerator().generate(
        context(game), profile("buy")
    ) == ()


def test_movement_history_penalizes_immediate_backtracking():
    memory = MovementHistoryMemory()
    for x in (1, 2, 1):
        memory.observe(state(roles=[role(10, x, 1, "worker")]))
    assert memory.view().backtrack_penalty(10, 2, 1) == 4.0
    assert memory.view().backtrack_penalty(10, 2, 0) == 0.0
