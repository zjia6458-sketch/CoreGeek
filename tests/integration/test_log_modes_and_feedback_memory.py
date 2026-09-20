import asyncio
import json
import logging

from fortress_agent.application.bootstrap import build_runtime


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []
    def emit(self, record):
        self.messages.append(record.getMessage())


def logger_with_capture(name):
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    capture = Capture()
    logger.addHandler(capture)
    return logger, capture


def payload(round_no, *, cmd_result="", action_results=None):
    return {
        "roundNo": round_no,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": [{"neutralType": "stone", "pos": {"x": 5, "y": 5}}],
        },
        "teamOur": {
            "type": "challenger",
            "teamId": "x",
            "teamName": "x",
            "goldNum": 0,
            "totalScore": 0,
            "playerTasks": [],
            "roles": [{
                "id": 10010,
                "pos": {"x": 5, "y": 4},
                "roleType": "worker",
                "health": 220,
                "attackPower": 0,
                "attackRange": 0,
                "backPackCapability": 100,
                "backpack": [],
            }],
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": []},
        "lastRoundRoleActionResults": action_results or {},
        "lastCmdResult": cmd_result,
        "worldNews": {"officialNews": "", "folkLegends": ""},
        "errors": [],
    }


def test_compact_and_full_modes_have_identical_agent_memory():
    medium_logger, medium_capture = logger_with_capture("test.mode.medium")
    high_logger, high_capture = logger_with_capture("test.mode.high")
    medium = build_runtime(logger=medium_logger, log_mode="medium")
    high = build_runtime(logger=high_logger, log_mode="high")

    for runtime in (medium, high):
        asyncio.run(runtime.handle_turn(payload(10)))
        asyncio.run(runtime.handle_turn(payload(
            11,
            cmd_result="[exitCode:0]\ncommand-ok",
            action_results={"10010": True},
        )))

    assert medium.feedback_memory.recent() == high.feedback_memory.recent()
    assert medium.world_memory.resource("zone:stone:5:5") == high.world_memory.resource("zone:stone:5:5")
    assert len(medium.experience_store.all()) == len(high.experience_store.all())
    assert len(medium_capture.messages) < len(high_capture.messages)


def test_medium_mode_keeps_human_round_summary_and_memory_but_hides_json_trace():
    logger, capture = logger_with_capture("test.mode.medium.keys")
    runtime = build_runtime(logger=logger, log_mode="medium")
    asyncio.run(runtime.handle_turn(payload(10)))
    asyncio.run(runtime.handle_turn(payload(
        11,
        cmd_result="[exitCode:0]\nHELLO_FROM_SANDBOX",
        action_results={"10010": True},
    )))
    text = "\n".join(capture.messages)
    assert "=====START=====" in text
    assert "Round 11" in text
    assert '"channel":"trace"' not in text
    assert runtime.feedback_memory.latest_command_result().endswith("HELLO_FROM_SANDBOX")

def test_high_mode_contains_policy_node_trace_while_medium_omits_it():
    medium_logger, medium_capture = logger_with_capture("test.mode.medium.nodes")
    high_logger, high_capture = logger_with_capture("test.mode.high.nodes")
    medium = build_runtime(logger=medium_logger, log_mode="medium")
    high = build_runtime(logger=high_logger, log_mode="high")
    asyncio.run(medium.handle_turn(payload(10)))
    asyncio.run(high.handle_turn(payload(10)))

    assert not any("policy_node_completed" in msg for msg in medium_capture.messages)
    assert any("policy_node_completed" in msg for msg in high_capture.messages)
