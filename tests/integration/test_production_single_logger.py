import json
import logging

from fortress_agent.application.bootstrap import (
    build_runtime,
)


class CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(
            record.getMessage()
        )


def test_production_runtime_emits_io_world_trace_experience_to_one_logger():
    logger = logging.getLogger(
        "test.production.single"
    )
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)

    capture = CaptureHandler()
    logger.addHandler(capture)

    runtime = build_runtime(
        logger=logger,
        log_mode="high",
    )

    import asyncio

    request = {
        "roundNo": 10,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": [{
                "neutralType": "stone",
                "pos": {"x": 5, "y": 5},
            }],
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
        "errors": [],
    }

    result = asyncio.run(
        runtime.handle_turn(request)
    )
    assert result.ok

    structured = []
    for message in capture.messages:
        try:
            structured.append(
                json.loads(message)
            )
        except Exception:
            pass

    channels = {
        item.get("channel")
        for item in structured
    }

    assert "io" in channels
    assert "trace" in channels
    assert "world_event" in channels
    assert "experience" in channels
