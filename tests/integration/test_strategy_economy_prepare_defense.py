import asyncio
import json

import pytest

from fortress_agent.application.bootstrap import build_runtime
from fortress_agent.game_rules.build_area import rocket_cluster_plan
from fortress_agent.protocol.codec import GameProtocolCodec


def base_payload(round_no: int, *, roles, zones=None, tasks=None, robots=None, gold=75):
    return {
        "roundNo": round_no,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": zones or [],
        },
        "teamOur": {
            "type": "challenger",
            "teamId": "x",
            "teamName": "x",
            "goldNum": gold,
            "totalScore": 0,
            "playerTasks": tasks or [],
            "roles": roles,
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": robots or []},
        "worldNews": {"officialNews": "", "folkLegends": ""},
        "errors": [],
    }


def character(role_id, x, y, role_type, backpack=None):
    return {
        "id": role_id,
        "pos": {"x": x, "y": y},
        "roleType": role_type,
        "health": 220 if role_type == "worker" else 200,
        "attackPower": 0,
        "attackRange": 0,
        "backPackCapability": 100 if role_type == "worker" else 40,
        "backpack": backpack or [],
    }


def building(role_id, x, y, role_type, attack=0, attack_range=0):
    return {
        "id": role_id,
        "pos": {"x": x, "y": y},
        "roleType": role_type,
        "health": 1500 if role_type == "station" else 1000,
        "attackPower": attack,
        "attackRange": attack_range,
        "backPackCapability": 0,
        "backpack": [],
        "level": 1,
        "cooldown": 0,
    }


def test_pioneer_in_economy_moves_toward_available_task_instead_of_local_loop():
    runtime = build_runtime()
    payload = base_payload(
        10,
        roles=[
            character(10010, 10, 16, "worker"),
            character(10011, 8, 20, "pioneer"),
        ],
        zones=[
            {"neutralType": "copper", "pos": {"x": 10, "y": 17}},
            {"neutralType": "challengerTaskPoint1", "pos": {"x": 14, "y": 14}},
        ],
        tasks=[{
            "taskType": "自进化类1",
            "taskPosition": {"x": 14, "y": 14},
            "coldDownRounds": 0,
            "scoreReward": 50,
            "goldReward": 30,
            "isValid": True,
            "timeoutRounds": 30,
        }],
    )
    result = asyncio.run(runtime.handle_turn(payload))
    assert result.ok
    response = json.loads(result.response_json)
    cmd = response["roleCommandMap"]["10011"]
    assert cmd["action"] == "move"
    target = cmd["targetPos"][0]
    before = abs(8 - 14) + abs(20 - 14)
    after = abs(target["x"] - 14) + abs(target["y"] - 14)
    assert after < before


def test_prepare_worker_far_from_base_moves_toward_base_ring():
    runtime = build_runtime()
    roles = [
        character(10010, 12, 31, "worker", ["iron"]),
        character(10011, 8, 20, "pioneer"),
        building(10013, 8, 20, "station"),
    ]
    payload = base_payload(63, roles=roles)
    result = asyncio.run(runtime.handle_turn(payload))
    assert result.ok
    response = json.loads(result.response_json)
    cmd = response["roleCommandMap"]["10010"]
    assert cmd["action"] == "move"
    target = cmd["targetPos"][0]
    before = max(abs(12 - 8), abs(31 - 20))
    after = max(abs(target["x"] - 8), abs(target["y"] - 20))
    assert after < before


def test_night_without_work_holds_instead_of_inventing_random_reposition():
    runtime = build_runtime()
    payload = base_payload(
        71,
        roles=[
            character(10010, 8, 19, "worker"),
            character(10011, 7, 20, "pioneer"),
            building(10013, 8, 20, "station"),
        ],
    )
    result = asyncio.run(runtime.handle_turn(payload))
    assert result.ok
    response = json.loads(result.response_json)
    assert response["roleCommandMap"] == {}
    assert result.error_code == "safety_hold"


def test_night_with_weapon_and_target_generates_attack():
    runtime = build_runtime()
    payload = base_payload(
        71,
        roles=[
            character(10010, 8, 19, "worker"),
            building(10013, 8, 20, "station"),
            building(10020, 9, 20, "gatling", attack=10, attack_range=4),
        ],
        robots=[{
            "id": 30001,
            "pos": {"x": 10, "y": 20},
            "roleType": "smallRobot",
            "health": 40,
            "abnormalState": "",
            "targetTeam": "challenger",
        }],
    )
    result = asyncio.run(runtime.handle_turn(payload))
    assert result.ok
    response = json.loads(result.response_json)
    assert response["roleCommandMap"]["10020"]["action"] == "attack"


def test_opening_primary_builder_builds_rocket_while_second_worker_keeps_economy_role():
    runtime = build_runtime()
    payload = base_payload(
        1,
        roles=[
            character(10010, 8, 21, "worker"),
            character(10011, 8, 23, "pioneer"),
            character(10012, 8, 22, "worker"),
            building(10013, 9, 22, "station"),
        ],
        zones=[
            {"neutralType": "iron", "pos": {"x": 5, "y": 24}},
            {"neutralType": "copper", "pos": {"x": 5, "y": 28}},
            {"neutralType": "stone", "pos": {"x": 9, "y": 13}},
            {"neutralType": "challengerTaskPoint1", "pos": {"x": 14, "y": 14}},
        ],
        tasks=[{
            "taskType": "自进化类1",
            "taskPosition": {"x": 14, "y": 14},
            "coldDownRounds": 0,
            "scoreReward": 50,
            "goldReward": 30,
            "isValid": True,
            "timeoutRounds": 30,
        }],
        gold=75,
    )
    result = asyncio.run(runtime.handle_turn(payload))
    response = json.loads(result.response_json)
    assert response["roleCommandMap"]["10010"]["action"] == "build"
    assert response["roleCommandMap"]["10010"]["name"] == "rocket"
    # Secondary Worker must not spend opening gold on a second weapon in the same turn.
    assert response["roleCommandMap"]["10012"]["action"] != "build"


def test_prepare_mode_starts_with_twenty_day_turns_remaining():
    runtime = build_runtime(prepare_margin_rounds=20)
    payload = base_payload(
        50,
        roles=[
            character(10010, 30, 28, "worker"),
            character(10011, 29, 28, "pioneer"),
            character(10012, 28, 28, "worker"),
            building(10013, 8, 20, "station"),
        ],
    )
    result = asyncio.run(runtime.handle_turn(payload))
    response = json.loads(result.response_json)
    # All three roles are now eligible to start returning instead of continuing exploration.
    assert response["roleCommandMap"]
    assert all(command["action"] == "move" for command in response["roleCommandMap"].values())


@pytest.mark.parametrize("existing", [(), ("rocket",), ("rocket", "rocket"), ("gatling", "railgun")])
def test_opening_fills_empty_slots_with_rockets_before_using_upgrade_voucher(existing):
    payload = base_payload(10, gold=25, roles=[
        character(10010, 7, 21, "worker", ["WeaponUpgradeVoucher1", "stone"]),
        building(10013, 9, 22, "station"),
    ])
    plan = rocket_cluster_plan(GameProtocolCodec().parse_state(payload).value)
    payload["teamOur"]["roles"][0]["pos"] = {"x": plan.controller[0], "y": plan.controller[1]}
    occupied = plan.rocket_cells[:len(existing)]
    payload["teamOur"]["roles"].extend(
        building(10040 + i, *cell, name) for i, (cell, name) in enumerate(zip(occupied, existing))
    )
    result = asyncio.run(build_runtime().handle_turn(payload))
    assert result.ok
    command = json.loads(result.response_json)["roleCommandMap"]["10010"]
    assert command["action"] == "build"
    assert command["name"] == "rocket"
    target = command["targetPos"][0]
    assert (target["x"], target["y"]) not in occupied
    assert (target["x"], target["y"]) != plan.controller


@pytest.mark.parametrize("base_x,base_y,wall_x", [(9, 22, 12), (30, 8, 28)])
def test_front_wall_voucher_used_before_station_and_other_walls(base_x, base_y, wall_x):
    payload = base_payload(10, gold=300, roles=[
        character(10010, wall_x, base_y - 1, "worker",
                  ["WallUpgradeVoucher1", "StationUpgradeVoucher1", "WeaponUpgradeVoucher2"]),
        building(10013, base_x, base_y, "station"),
        *[{**building(10040 + i, base_x - 1, base_y - i, "rocket"), "level": 2} for i in range(3)],
        building(10100, wall_x, base_y, "wall"),
    ])
    result = asyncio.run(build_runtime().handle_turn(payload))
    assert result.ok
    command = json.loads(result.response_json)["roleCommandMap"]["10010"]
    assert command["action"] == "use"
    assert command["name"] == "WallUpgradeVoucher1"
    assert command["targetPos"] == [{"x": wall_x, "y": base_y}]


def test_worker_finishes_vendor_trip_and_partial_sales_across_real_turns():
    runtime = build_runtime()
    x, y = 5, 5
    backpack = ["iron"] * 4 + ["copper"]
    sold = []
    for round_no in range(10, 20):
        payload = base_payload(round_no, gold=0,
            roles=[character(10010, x, y, "worker", backpack)],
            zones=[{"neutralType": "vendor", "pos": {"x": 1, "y": 5}},
                   {"neutralType": "iron", "pos": {"x": 6, "y": 5}}])
        payload["vendorShopList"] = [{"name": "iron", "price": 3}, {"name": "copper", "price": 5}]
        payload["lastRoundRoleActionResults"] = {"10010": True} if round_no > 10 else {}
        result = asyncio.run(runtime.handle_turn(payload))
        assert result.ok
        command = json.loads(result.response_json)["roleCommandMap"]["10010"]
        if command["action"] == "move":
            target = command["targetPos"][0]
            old_distance = max(abs(x - 1), abs(y - 5))
            x, y = target["x"], target["y"]
            assert max(abs(x - 1), abs(y - 5)) < old_distance
        else:
            assert command["action"] == "sell"
            sold.append(command["name"])
            backpack = [item for item in backpack if item != command["name"]]
            if not backpack:
                break
    assert set(sold) == {"iron", "copper"}
    assert not backpack


def test_worker_mines_at_night_then_retreats_when_robot_approaches():
    runtime = build_runtime()
    payload = base_payload(71, gold=0, roles=[character(10010, 2, 2, "worker")],
        zones=[{"neutralType": "iron", "pos": {"x": 3, "y": 2}}],
        robots=[{**building(20000, 20, 16, "smallrobot", attack=5, attack_range=3), "health": 40}])
    first = asyncio.run(runtime.handle_turn(payload))
    assert first.ok
    assert json.loads(first.response_json)["roleCommandMap"]["10010"]["action"] == "collect"
    payload["roundNo"] = 72
    payload["robot"]["roles"][0]["pos"] = {"x": 7, "y": 2}
    payload["lastRoundRoleActionResults"] = {"10010": True}
    second = asyncio.run(runtime.handle_turn(payload))
    assert second.ok
    command = json.loads(second.response_json)["roleCommandMap"]["10010"]
    assert command["action"] == "move"
    target = command["targetPos"][0]
    assert max(abs(target["x"] - 7), abs(target["y"] - 2)) > 5
