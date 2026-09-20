import asyncio
import json

from fortress_agent.application.bootstrap import build_runtime


def _character(role_id, x, y, role_type):
    return {
        "id": role_id,
        "pos": {"x": x, "y": y},
        "roleType": role_type,
        "health": 220 if role_type == "worker" else 200,
        "attackPower": 0,
        "attackRange": 0,
        "backPackCapability": 100 if role_type == "worker" else 40,
        "backpack": [],
    }


def _station():
    return {
        "id": 10013,
        "pos": {"x": 9, "y": 22},
        "roleType": "station",
        "health": 1500,
        "attackPower": 0,
        "attackRange": 0,
        "backPackCapability": 0,
        "backpack": [],
        "level": 1,
        "cooldown": 0,
    }


def _payload(round_no, *, last_cmd="", llm_resp=""):
    return {
        "roundNo": round_no,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": [
                {"neutralType": "challengerTaskPoint1", "pos": {"x": 14, "y": 14}},
            ],
        },
        "teamOur": {
            "type": "challenger",
            "teamId": "x",
            "teamName": "x",
            "goldNum": 50,
            "totalScore": 0,
            "playerTasks": [],
            "roles": [
                _character(10010, 8, 21, "worker"),
                _character(10011, 13, 15, "pioneer"),
                _character(10012, 8, 23, "worker"),
                _station(),
            ],
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": []},
        "phaseTask": "查询北京文化遗产，并按照任务要求返回完整字段。",
        "lastCmdResult": last_cmd,
        "llmResp": llm_resp,
        "worldNews": {"officialNews": "", "folkLegends": ""},
        "errors": [],
        "vendorShopList": [],
        "weaponShopList": [],
    }


def test_active_task_starts_execute_cmd_and_task_prompt():
    runtime = build_runtime()
    result = asyncio.run(runtime.handle_turn(_payload(10)))
    assert result.ok
    response = json.loads(result.response_json)
    assert "find /tmp/selfEvolutionTask" in response["executeCmd"]
    assert '"schema_version":"task-1.0"' in response["prompt"]


def test_task_llm_execute_command_is_sent():
    runtime = build_runtime()
    asyncio.run(runtime.handle_turn(_payload(10)))
    advice = json.dumps({
        "schema_version": "task-1.0",
        "source_round": 10,
        "action": "execute",
        "execute_cmd": "cat /tmp/selfEvolutionTask/API_DOCS.md | head -300",
        "task_answer": "",
        "confidence": 0.9,
        "short_reason": "读取 API 文档",
    }, ensure_ascii=False)
    result = asyncio.run(runtime.handle_turn(_payload(
        11,
        last_cmd="[exitCode:0]\n/tmp/selfEvolutionTask/API_DOCS.md",
        llm_resp=advice,
    )))
    response = json.loads(result.response_json)
    assert response["executeCmd"] == "cat /tmp/selfEvolutionTask/API_DOCS.md | head -300"


def test_task_llm_submit_overrides_pioneer_move_and_clears_execute_cmd():
    runtime = build_runtime()
    asyncio.run(runtime.handle_turn(_payload(10)))
    advice = json.dumps({
        "schema_version": "task-1.0",
        "source_round": 10,
        "action": "submit",
        "execute_cmd": "",
        "task_answer": '{"city":"北京","world_heritage_count":7}',
        "confidence": 0.95,
        "short_reason": "字段已经齐全",
    }, ensure_ascii=False)
    result = asyncio.run(runtime.handle_turn(_payload(11, llm_resp=advice)))
    response = json.loads(result.response_json)
    assert response["roleCommandMap"]["10011"]["action"] == "submitAnswer"
    assert "world_heritage_count" in response["roleCommandMap"]["10011"]["taskAnswer"]
    assert response["executeCmd"] == ""
