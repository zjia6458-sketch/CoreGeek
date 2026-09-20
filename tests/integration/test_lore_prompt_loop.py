import asyncio
import json

from fortress_agent.application.runtime import FortressAgentRuntime


def response(round_no):
    return {
        "roundNo": round_no,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": [],
        },
        "teamOur": {
            "type": "challenger",
            "teamId": "x",
            "teamName": "x",
            "goldNum": 0,
            "totalScore": 0,
            "playerTasks": [],
            "roles": [{
                "id": 10011,
                "pos": {"x": 10, "y": 12},
                "roleType": "pioneer",
                "health": 200,
                "attackPower": 0,
                "attackRange": 0,
                "backPackCapability": 40,
                "backpack": [],
            }],
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": []},
        "worldNews": {
            "officialNews": "",
            "folkLegends": "西部有一石门，门需三钥",
        },
        "errors": [],
    }


def test_new_folk_legend_automatically_populates_one_structured_llm_prompt():
    runtime = FortressAgentRuntime()

    first = asyncio.run(
        runtime.handle_turn(
            response(10)
        )
    )
    assert first.ok

    first_payload = json.loads(
        first.response_json
    )

    assert first_payload["prompt"]
    assert (
        runtime.llm_budget.used_normal_calls
        == 1
    )

    second = asyncio.run(
        runtime.handle_turn(
            response(11)
        )
    )
    assert second.ok

    second_payload = json.loads(
        second.response_json
    )

    assert second_payload["prompt"] == ""
    assert (
        runtime.llm_budget.used_normal_calls
        == 1
    )
