import json
import logging

from fortress_agent.observability.logger import (
    LoggerJsonWriter,
    LoggerTraceSink,
)
from fortress_agent.observability.trace import (
    TraceEvent,
)


class CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(
            record.getMessage()
        )


def test_logger_json_writer_uses_supplied_root_logger_only():
    logger = logging.getLogger(
        "test.single.logger"
    )
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)

    capture = CaptureHandler()
    logger.addHandler(capture)

    writer = LoggerJsonWriter(
        channel="experience",
        logger=logger,
        mode="high",
    )
    writer.write({
        "record_type": "outcome",
        "correlation_id": "r11:attempt:2",
        "value": 1.5,
    })

    assert len(capture.messages) == 1

    payload = json.loads(
        capture.messages[0]
    )

    assert payload["channel"] == "experience"
    assert payload["record_type"] == "outcome"
    assert payload["correlation_id"] == "r11:attempt:2"


def test_logger_trace_sink_emits_structured_trace_record():
    logger = logging.getLogger(
        "test.trace.logger"
    )
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)

    capture = CaptureHandler()
    logger.addHandler(capture)

    sink = LoggerTraceSink(
        logger=logger,
        mode="high",
    )
    sink.emit(
        TraceEvent(
            kind="strategy_selected",
            round_id=10,
            correlation_id="r10:attempt:1",
            data={
                "strategy_id": "economy"
            },
        )
    )

    payload = json.loads(
        capture.messages[0]
    )

    assert payload["channel"] == "trace"
    assert payload["record_type"] == "trace"
    assert payload["event"]["kind"] == "strategy_selected"


def test_compact_logger_keeps_terrain_rule_learning_event():
    from fortress_agent.observability.logger import LogMode

    logger = logging.getLogger("test.terrain.rule.compact")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    capture = CaptureHandler()
    logger.addHandler(capture)

    sink = LoggerTraceSink(logger=logger, mode=LogMode.HIGH)
    sink.emit(TraceEvent(
        kind="terrain_rule_learned",
        round_id=16,
        correlation_id="r16:attempt:2",
        data={
            "terrain_type": "defenderTaskPoint1",
            "property": "traversability",
            "value": "impassable",
            "scope": "all_neutral_zones_of_this_type",
        },
    ))

    assert len(capture.messages) == 1
    payload = json.loads(capture.messages[0])
    assert payload["event"]["kind"] == "terrain_rule_learned"
    assert payload["event"]["data"]["terrain_type"] == "defenderTaskPoint1"


def test_compact_logger_keeps_action_execution_failed_trigger():
    from fortress_agent.observability.logger import LogMode

    logger = logging.getLogger("test.action.execution.failed.compact")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    capture = CaptureHandler()
    logger.addHandler(capture)

    sink = LoggerTraceSink(logger=logger, mode=LogMode.HIGH)
    sink.emit(TraceEvent(
        kind="action_execution_failed",
        round_id=16,
        correlation_id="r16:attempt:16",
        data={
            "role_id": "20011",
            "action_type": "MOVE",
            "reason": "role_action_result_false",
        },
    ))

    assert len(capture.messages) == 1
    payload = json.loads(capture.messages[0])
    assert payload["event"]["kind"] == "action_execution_failed"
    assert payload["event"]["data"]["role_id"] == "20011"
