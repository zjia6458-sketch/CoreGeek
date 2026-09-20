import asyncio
import json

from fortress_agent.application.bootstrap import build_runtime


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


def test_night_without_weapon_uses_safe_reposition_instead_of_empty_team_response():
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
    # V0.5.3: defense must not silently idle for an entire night. Without a
    # weapon, roles use verified traversable repositioning toward the base.
    assert response["roleCommandMap"]
    assert all(command["action"] == "move" for command in response["roleCommandMap"].values())


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
