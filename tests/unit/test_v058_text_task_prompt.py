from dataclasses import replace
import json

from fortress_agent.tasks.session import TaskSessionCoordinator
from fortress_agent.protocol.codec import GameProtocolCodec


def _payload(*, round_no=10, phase_task, last_cmd="", llm_resp=""):
    return {
        "roundNo": round_no,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": [{"neutralType": "challengerTaskPoint1", "pos": {"x": 14, "y": 14}}],
        },
        "teamOur": {
            "type": "challenger", "teamId": "x", "teamName": "x", "goldNum": 50, "totalScore": 0,
            "playerTasks": [],
            "roles": [{
                "id": 10011, "pos": {"x": 13, "y": 15}, "roleType": "pioneer", "health": 200,
                "attackPower": 0, "attackRange": 0, "backPackCapability": 40, "backpack": [],
            }],
        },
        "teamEnemy": {"roles": []}, "robot": {"roles": []},
        "phaseTask": phase_task, "lastCmdResult": last_cmd, "llmResp": llm_resp,
        "worldNews": {"officialNews": "", "folkLegends": ""}, "errors": [],
        "vendorShopList": [], "weaponShopList": [],
    }


def _state(**kwargs):
    result = GameProtocolCodec().parse_state(_payload(**kwargs))
    assert result.ok and result.value is not None
    return result.value


def test_text_task_prompt_is_chinese_and_text_first():
    coordinator = TaskSessionCoordinator()
    state = _state(phase_task="阅读以下文本并总结主旨：长城是中国古代重要防御工程。")
    plan = coordinator.plan(state)
    assert plan is not None
    assert plan.execute_cmd == ""
    assert "文本类任务" in plan.prompt
    assert "信息足够就直接 submit" in plan.prompt
    assert "严禁为了纯文本题无意义地 find/ls/cat" in plan.prompt
    assert "完整性检查" in plan.prompt
    assert "short_reason" in plan.prompt


def test_tool_task_still_discovers_sandbox_files_on_first_turn():
    coordinator = TaskSessionCoordinator()
    state = _state(phase_task="读取 API 文档，调用 localhost 接口查询北京文化遗产并返回 JSON。")
    plan = coordinator.plan(state)
    assert plan is not None
    assert "find /tmp/selfEvolutionTask" in plan.execute_cmd
    assert "工具类任务" in plan.prompt


def test_task_parser_accepts_short_chinese_prefix_before_valid_json():
    coordinator = TaskSessionCoordinator()
    first = coordinator.plan(_state(phase_task="阅读以下文本并回答：2+2 等于多少？"))
    assert first is not None
    raw = '我已经核对完成。\n' + json.dumps({
        "schema_version": "task-1.0",
        "source_round": 10,
        "action": "submit",
        "execute_cmd": "",
        "task_answer": "4",
        "confidence": 0.99,
        "short_reason": "题面信息足够，直接提交",
    }, ensure_ascii=False)
    second_state = replace(
        _state(round_no=11, phase_task="阅读以下文本并回答：2+2 等于多少？"),
        raw_llm_response=raw,
    )
    plan = coordinator.plan(second_state)
    assert plan is not None
    assert plan.stage == "submit"
    assert plan.task_answer == "4"


def test_text_prompt_requires_exact_output_and_no_invented_fields():
    coordinator = TaskSessionCoordinator()
    plan = coordinator.plan(_state(
        phase_task='根据材料提取字段，必须返回 JSON：{"name": string, "count": integer}。材料：苹果数量为3。'
    ))
    assert plan is not None
    assert "缺证据时不要编造" in plan.prompt
    assert "键名" in plan.prompt
    assert "task_answer 必须严格满足" in plan.prompt
