import asyncio
import json

from fortress_agent.application.runtime import FortressAgentRuntime


def payload(round_no, *, pos, error_text="", legal_result=None):
    role_results = {} if legal_result is None else {"20011": legal_result}
    return {
        "roundNo": round_no,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": [{
                "neutralType": "defenderTaskPoint1",
                "pos": {"x": 23, "y": 14},
            }],
        },
        "teamOur": {
            "type": "defender",
            "teamId": "4737",
            "teamName": "B",
            "goldNum": 0,
            "totalScore": 0,
            "playerTasks": [{
                "taskType": "自进化类1",
                "taskPosition": {"x": 23, "y": 14},
                "coldDownRounds": 0,
                "scoreReward": 50,
                "goldReward": 30,
                "isValid": True,
                "timeoutRounds": 50,
            }],
            "roles": [{
                "id": 20011,
                "pos": {"x": pos[0], "y": pos[1]},
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
        "lastRoundRoleActionResults": role_results,
        "worldNews": {"officialNews": "", "folkLegends": ""},
        "errors": ([{"errorCode": 4, "description": error_text}] if error_text else []),
    }


def test_taskpoint_static_rule_blocks_move_even_when_server_text_mismatches_previous_action():
    runtime = FortressAgentRuntime()

    # At an adjacent access cell the correct command is acceptTask, not MOVE
    # onto the task-point tile.
    first = asyncio.run(runtime.handle_turn(payload(15, pos=(23, 13))))
    assert first.ok
    first_wire = json.loads(first.response_json)
    assert first_wire["roleCommandMap"]["20011"]["action"] == "acceptTask"

    # Server text claims an old MOVE(23,14), but this runtime actually sent
    # acceptTask.  Strict feedback correlation must NOT turn mismatched text
    # into learned memory.  The static TaskPoint rule still keeps the tile safe.
    error = (
        "[COMMAND_ERROR] role 20011 wants MOVE to (23,14), "
        "but target is impassable terrain [defenderTaskPoint1]"
    )
    second = asyncio.run(runtime.handle_turn(
        payload(16, pos=(23, 13), error_text=error, legal_result=False)
    ))
    assert second.ok

    view = runtime.feedback_memory
    latest = view.latest()
    assert latest is not None
    assert latest.action_failures
    assert latest.command_errors == ()
    assert not view.is_terrain_impassable("defenderTaskPoint1")

    second_wire = json.loads(second.response_json)
    command = second_wire["roleCommandMap"].get("20011")
    assert command is None or not (
        command.get("action") == "move"
        and command.get("targetPos") == [{"x": 23, "y": 14}]
    )
