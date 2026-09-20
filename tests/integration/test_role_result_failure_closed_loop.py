import asyncio
import json
import logging

from fortress_agent.application.bootstrap import build_runtime


class CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def payload(round_no, *, pos, result=None, error_description=""):
    return {
        "roundNo": round_no,
        "mapInfo": {"width": 41, "height": 32, "zones": []},
        "teamOur": {
            "type": "defender",
            "teamId": "4737",
            "teamName": "B",
            "goldNum": 0,
            "totalScore": 0,
            "playerTasks": [],
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
        "lastRoundRoleActionResults": (
            {} if result is None else {"20011": result}
        ),
        "errors": (
            [] if not error_description else [{
                "errorCode": 4,
                "description": error_description,
            }]
        ),
        "worldNews": {
            "officialNews": "",
            "folkLegends": "",
        },
    }


def test_false_role_result_logs_failure_and_suppresses_exact_retry_without_text_parser():
    logger = logging.getLogger("test.role.result.closed.loop")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    capture = CaptureHandler()
    logger.addHandler(capture)

    runtime = build_runtime(logger=logger, log_mode="high")

    first = asyncio.run(runtime.handle_turn(payload(1, pos=(5, 5))))
    assert first.ok

    first_wire = json.loads(first.response_json)
    first_command = first_wire["roleCommandMap"].get("20011")
    assert first_command is not None
    assert first_command["action"] == "move"
    failed_target = first_command["targetPos"][0]

    second = asyncio.run(runtime.handle_turn(
        payload(2, pos=(5, 5), result=False)
    ))
    assert second.ok

    # Compact stdout contains an explicit trigger independent of error text.
    structured = []
    for message in capture.messages:
        try:
            structured.append(json.loads(message))
        except Exception:
            pass

    failures = [
        item for item in structured
        if item.get("channel") == "trace"
        and item.get("event", {}).get("kind") == "action_execution_failed"
    ]
    assert failures
    event = failures[-1]["event"]
    assert event["data"]["role_id"] == "20011"
    assert event["data"]["reason"] == "role_action_result_false"

    # The exact failed move cannot be immediately repeated.
    second_wire = json.loads(second.response_json)
    second_command = second_wire["roleCommandMap"].get("20011")
    if second_command and second_command.get("action") == "move":
        assert second_command["targetPos"][0] != failed_target

    # Failure is attached to the previous Experience Outcome.
    prior = [
        exp for exp in runtime.experience_store.all()
        if exp.round_id == 1 and str(exp.action.actor_id) == "20011"
    ]
    assert prior
    outcome = runtime.experience_store.outcome_for(prior[0].decision_id)
    assert outcome is not None
    assert outcome.action_legal is False
    assert outcome.action_failure_signatures


def test_real_server_error_description_without_prefix_enriches_failure_and_prompt():
    logger = logging.getLogger("test.real.server.error.description")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(CaptureHandler())

    runtime = build_runtime(logger=logger, log_mode="high")
    first = asyncio.run(runtime.handle_turn(payload(15, pos=(23, 13))))
    assert first.ok
    first_wire = json.loads(first.response_json)
    first_command = first_wire["roleCommandMap"]["20011"]
    assert first_command["action"] == "move"
    actual_target = first_command["targetPos"][0]
    tx, ty = actual_target["x"], actual_target["y"]

    raw = (
        f"role 20011 wants MOVE to ({tx},{ty}), "
        "but target is impassable terrain [mysteryTerrain]"
    )
    second = asyncio.run(runtime.handle_turn(
        payload(16, pos=(23, 13), result=False, error_description=raw)
    ))
    assert second.ok

    latest = runtime.feedback_memory.latest()
    assert latest is not None
    assert latest.command_errors
    assert latest.action_failures
    assert runtime.feedback_memory.is_terrain_impassable("mysteryTerrain")
    assert runtime.feedback_memory.impassable_cells() == ()

    wire = json.loads(second.response_json)
    prompt = wire.get("prompt", "")
    assert "terrain type [mysteryTerrain] is IMPASSABLE" in prompt
    assert "ANY neutral-zone cell" in prompt
    assert "coordinate that exposed this rule is evidence only" in prompt
    assert "Never infer safety rules from downloaded logs" in prompt



def test_mismatched_server_error_text_cannot_create_permanent_block():
    logger = logging.getLogger("test.mismatched.server.error")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(CaptureHandler())

    runtime = build_runtime(logger=logger, log_mode="high")

    first = asyncio.run(runtime.handle_turn(payload(1, pos=(5, 5))))
    assert first.ok
    first_wire = json.loads(first.response_json)
    first_command = first_wire["roleCommandMap"]["20011"]
    actual_target = first_command["targetPos"][0]

    # Deliberately describe a different target than the one our program sent.
    raw = (
        "role 20011 wants MOVE to (23,14), "
        "but target is impassable terrain [defenderTaskPoint1]"
    )
    second = asyncio.run(runtime.handle_turn(
        payload(2, pos=(5, 5), result=False, error_description=raw)
    ))
    assert second.ok

    latest = runtime.feedback_memory.latest()
    assert latest is not None
    assert latest.action_failures
    assert latest.command_errors == ()
    assert runtime.feedback_memory.impassable_cells() == ()
    assert not runtime.feedback_memory.is_terrain_impassable("defenderTaskPoint1")

    # The action we really sent is still temporarily suppressed.
    second_wire = json.loads(second.response_json)
    second_command = second_wire["roleCommandMap"].get("20011")
    if second_command and second_command.get("action") == "move":
        assert second_command["targetPos"][0] != actual_target
