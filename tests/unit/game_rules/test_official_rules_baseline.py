from fortress_agent.domain.state import BuildingState, GameState, Position
from fortress_agent.game_rules.build_area import (
    BuildAreaType,
    StationDefenseBuildAreaPolicy,
    VerifiedBuildAreaPolicy,
    station_defense_cells,
)
from fortress_agent.game_rules.catalog import (
    CHARACTER_RULES,
    KNOWN_WEAPON_SHOP_PRICES,
    ROBOT_RULES,
    building_rule,
    building_max_hp,
    weapon_attack_range,
)
from fortress_agent.game_rules.constants import (
    DAY_TURNS,
    NIGHT_TURNS,
    MAX_ROUNDS,
    SHARED_VISION_RANGE,
    MINE_COLLECTIONS_BEFORE_REFRESH,
    GLOBAL_WEAPON_LIMIT,
    WALL_LIMIT,
    TASK_REFRESH_COOLDOWN_ROUNDS,
    ROBOT_SUMMON_ORDER_DAILY_LIMIT,
    MAX_RESPONSE_ANOMALIES,
)
from fortress_agent.game_rules.feedback import FeedbackClass, classify_role_action_result
from fortress_agent.game_rules.geometry import chebyshev_distance, is_adjacent8, neighbors8
from fortress_agent.game_rules.scoring import completed_task_score, partial_task_score, survival_day_score


def _minimal_state(*, buildings=()):
    return GameState(
        round_id=1,
        day=1,
        phase="day",
        phase_round=1,
        turns_until_phase_change=69,
        score_self=0,
        score_opponent=0,
        anomaly_count=0,
        characters=(),
        enemies=(),
        buildings=tuple(buildings),
        resources=(),
        tasks=(),
        observed_cells=(),
        news=(),
        rumors=(),
        market_prices={},
    )


def test_official_time_and_safety_constants_are_frozen():
    assert (DAY_TURNS, NIGHT_TURNS, MAX_ROUNDS) == (70, 60, 1300)
    assert SHARED_VISION_RANGE == 4
    assert MINE_COLLECTIONS_BEFORE_REFRESH == 10
    assert GLOBAL_WEAPON_LIMIT == 3
    assert WALL_LIMIT == 20
    assert TASK_REFRESH_COOLDOWN_ROUNDS == 30
    assert ROBOT_SUMMON_ORDER_DAILY_LIMIT == 10
    assert MAX_RESPONSE_ANOMALIES == 5


def test_movement_is_eight_direction_chebyshev():
    center = Position(5, 5)
    around = neighbors8(5, 5)
    assert len(around) == 8
    assert len(set(around)) == 8
    assert is_adjacent8(center, Position(4, 4))
    assert chebyshev_distance(center, Position(4, 4)) == 1
    assert chebyshev_distance(center, Position(7, 6)) == 2


def test_character_and_robot_authoritative_stats():
    assert CHARACTER_RULES["pioneer"].max_hp == 200
    assert CHARACTER_RULES["pioneer"].backpack_capacity == 40
    assert CHARACTER_RULES["worker"].max_hp == 220
    assert CHARACTER_RULES["worker"].initial_count == 2
    assert ROBOT_RULES["smallrobot"].max_hp == 40
    assert ROBOT_RULES["middlerobot"].score_value == 2
    assert ROBOT_RULES["largerobot"].attack == 20
    assert ROBOT_RULES["bossrobot"].max_hp == 800
    assert all(rule.attack_range == 3 for rule in ROBOT_RULES.values())


def test_building_cost_limit_hp_and_weapon_ranges():
    assert building_rule("wall").build_items == (("stone", 1),)
    assert building_rule("wall").max_count == 20
    assert building_rule("gatling").build_gold_cost == 25
    assert building_rule("railgun").build_gold_cost == 25
    assert building_rule("rocket").build_gold_cost == 25
    assert building_rule("rocket").max_count == 3
    assert building_max_hp("station", 3) == 4500
    assert building_max_hp("wall", 2) == 1500
    assert [weapon_attack_range("gatling", x) for x in (1, 2, 3)] == [3, 5, 7]
    assert [weapon_attack_range("railgun", x) for x in (1, 2, 3)] == [6, 8, 10]
    assert weapon_attack_range("rocket", 1) == 10
    assert weapon_attack_range("rocket", 2) == 15
    assert weapon_attack_range("rocket", 3) is None


def test_known_shop_prices_match_official_rules():
    assert KNOWN_WEAPON_SHOP_PRICES["Medicine"] == 10
    assert KNOWN_WEAPON_SHOP_PRICES["WallFixer"] == 10
    assert KNOWN_WEAPON_SHOP_PRICES["Bomb"] == 100
    assert KNOWN_WEAPON_SHOP_PRICES["WeaponUpgradeVoucher1"] == 100
    assert KNOWN_WEAPON_SHOP_PRICES["WeaponUpgradeVoucher2"] == 150
    assert KNOWN_WEAPON_SHOP_PRICES["BossRobotSummonOrder"] == 200


def test_station_template_requires_station_or_explicit_override():
    policy = VerifiedBuildAreaPolicy()
    assert not policy.permits(building_name="wall", target=(5, 5), state=_minimal_state())
    assert not policy.permits(building_name="gatling", target=(5, 5), state=_minimal_state())

    existing = BuildingState(
        building_id=10020,
        building_type="gatling",
        position=Position(5, 5),
        hp=1000,
        max_hp=1000,
        owner="self",
        cooldown_remaining=0,
        level=1,
    )
    state = _minimal_state(buildings=(existing,))
    assert policy.permits(building_name="rocket", target=(5, 5), state=state)



def test_station_2x2_generates_12_weapon_cells_and_20_wall_cells():
    station = BuildingState(
        building_id=10013,
        building_type="station",
        position=Position(10, 10),
        hp=1500,
        max_hp=1500,
        owner="self",
        cooldown_remaining=0,
        level=1,
        footprint_width=2,
        footprint_height=2,
        footprint_anchor="top_left",
    )
    state = _minimal_state(buildings=(station,))
    policy = StationDefenseBuildAreaPolicy()

    weapon_cells = station_defense_cells(state, ring_distance=1)
    wall_cells = station_defense_cells(state, ring_distance=2)

    assert len(weapon_cells) == 12
    assert len(wall_cells) == 20
    assert weapon_cells.isdisjoint(wall_cells)

    # 0 = station footprint.
    assert policy.classify(target=(10, 10), state=state) is BuildAreaType.STATION
    assert policy.classify(target=(11, 9), state=state) is BuildAreaType.STATION
    # 1 = weapon ring.
    assert policy.classify(target=(9, 10), state=state) is BuildAreaType.WEAPON
    assert policy.classify(target=(12, 8), state=state) is BuildAreaType.WEAPON
    # 2 = wall ring.
    assert policy.classify(target=(8, 10), state=state) is BuildAreaType.WALL
    assert policy.classify(target=(13, 7), state=state) is BuildAreaType.WALL

    assert policy.permits(building_name="rocket", target=(9, 10), state=state)
    assert policy.permits(building_name="railgun", target=(12, 8), state=state)
    assert not policy.permits(building_name="wall", target=(9, 10), state=state)
    assert policy.permits(building_name="wall", target=(8, 10), state=state)
    assert not policy.permits(building_name="rocket", target=(8, 10), state=state)


def test_station_template_matches_documented_222_211_210_shape():
    station = BuildingState(
        building_id=10013,
        building_type="station",
        position=Position(10, 10),
        hp=1500,
        max_hp=1500,
        owner="self",
        cooldown_remaining=0,
        level=1,
        footprint_width=2,
        footprint_height=2,
        footprint_anchor="top_left",
    )
    state = _minimal_state(buildings=(station,))
    policy = StationDefenseBuildAreaPolicy()

    rendered = []
    for y in range(12, 6, -1):
        row = []
        for x in range(8, 14):
            area = policy.classify(target=(x, y), state=state)
            row.append({
                BuildAreaType.STATION: "0",
                BuildAreaType.WEAPON: "1",
                BuildAreaType.WALL: "2",
                BuildAreaType.NONE: ".",
            }[area])
        rendered.append("".join(row))

    assert rendered == [
        "222222",
        "211112",
        "210012",
        "210012",
        "211112",
        "222222",
    ]

def test_verified_blue_and_yellow_cells_are_type_specific():
    policy = VerifiedBuildAreaPolicy.from_config(
        weapon_cells=((4, 4),),
        wall_cells=((6, 6),),
    )
    state = _minimal_state()
    assert policy.permits(building_name="gatling", target=(4, 4), state=state)
    assert not policy.permits(building_name="wall", target=(4, 4), state=state)
    assert policy.permits(building_name="wall", target=(6, 6), state=state)
    assert not policy.permits(building_name="rocket", target=(6, 6), state=state)


def test_role_action_false_is_execution_failure_not_response_anomaly():
    assert classify_role_action_result(False) is FeedbackClass.ACTION_EXECUTION_FAILURE
    assert classify_role_action_result(True) is FeedbackClass.ACTION_EXECUTION_SUCCESS
    assert classify_role_action_result(None) is FeedbackClass.UNKNOWN
    assert classify_role_action_result(False) is not FeedbackClass.RESPONSE_ANOMALY


def test_official_scoring_formula_helpers():
    assert completed_task_score(
        task_score_reward=50,
        timeout_rounds=20,
        accepted_round=10,
        completed_round=20,
    ) == 60
    assert partial_task_score(task_score_reward=50, pass_rate=0.6) == 30
    assert survival_day_score(day=4, base_alive=True) == 40
    assert survival_day_score(day=4, base_alive=False) == 0
