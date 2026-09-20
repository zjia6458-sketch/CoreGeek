import asyncio
import json

from fortress_agent.application.bootstrap import build_runtime


def test_verified_build_recipe_unlocks_build_candidate_in_prepare():
    runtime = build_runtime(
        build_recipes={
            "wall": {
                "required_items": {"stone": 1},
                "strategic_value": 8.0,
            }
        },
        wall_build_cells=((7, 21),),
    )
    payload = {
        "roundNo": 63,
        "mapInfo": {"width": 41, "height": 32, "zones": []},
        "teamOur": {
            "type": "challenger",
            "teamId": "x",
            "teamName": "x",
            "goldNum": 0,
            "totalScore": 0,
            "playerTasks": [],
            "roles": [
                {
                    "id": 10010,
                    "pos": {"x": 7, "y": 20},
                    "roleType": "worker",
                    "health": 220,
                    "attackPower": 0,
                    "attackRange": 0,
                    "backPackCapability": 100,
                    "backpack": ["stone"],
                },
                {
                    "id": 10013,
                    "pos": {"x": 8, "y": 20},
                    "roleType": "station",
                    "health": 1500,
                    "attackPower": 0,
                    "attackRange": 0,
                    "backPackCapability": 0,
                    "backpack": [],
                    "level": 1,
                    "cooldown": 0,
                },
            ],
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": []},
        "worldNews": {"officialNews": "", "folkLegends": ""},
        "errors": [],
    }
    result = asyncio.run(runtime.handle_turn(payload))
    assert result.ok
    response = json.loads(result.response_json)
    assert response["roleCommandMap"]["10010"]["action"] == "build"
    assert response["roleCommandMap"]["10010"]["name"] == "wall"
