import asyncio
import json

from fortress_agent.application.bootstrap import build_runtime


def test_loaded_worker_moves_toward_vendor_instead_of_gathering_forever():
    runtime = build_runtime()
    payload = {
        "roundNo": 30,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": [
                {"neutralType": "copper", "pos": {"x": 10, "y": 17}},
                {"neutralType": "vendor", "pos": {"x": 20, "y": 16}},
            ],
        },
        "teamOur": {
            "type": "challenger",
            "teamId": "x",
            "teamName": "x",
            "goldNum": 75,
            "totalScore": 0,
            "playerTasks": [],
            "roles": [{
                "id": 10010,
                "pos": {"x": 10, "y": 16},
                "roleType": "worker",
                "health": 220,
                "attackPower": 0,
                "attackRange": 0,
                "backPackCapability": 100,
                "backpack": ["copper"] * 10,
            }],
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": []},
        "vendorShopList": [
            {"name": "stone", "price": 1},
            {"name": "iron", "price": 3},
            {"name": "copper", "price": 5},
        ],
        "worldNews": {"officialNews": "", "folkLegends": ""},
        "errors": [],
    }
    result = asyncio.run(runtime.handle_turn(payload))
    assert result.ok
    response = json.loads(result.response_json)
    cmd = response["roleCommandMap"]["10010"]
    assert cmd["action"] == "move"
    target = cmd["targetPos"][0]
    assert max(abs(target["x"] - 20), abs(target["y"] - 16)) < 10
