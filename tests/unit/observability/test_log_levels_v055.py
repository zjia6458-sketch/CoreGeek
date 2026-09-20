import io
import logging
import json

from fortress_agent.observability.logger import LoggerJsonWriter, LoggerTraceSink
from fortress_agent.observability.trace import TraceEvent


def _logger(name):
    stream = io.StringIO()
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger, stream


def _summary_event():
    return TraceEvent(
        kind="round_human_summary",
        round_id=9,
        data={
            "day": 1,
            "phase": "DAY",
            "gold": 50,
            "score": 0,
            "strategy": "active_task",
            "node_chain": ["runtime_gate", "strategy", "candidates", "rank", "finalize"],
            "roles": [{"kind":"pioneer","id":"10011","x":13,"y":15,"hp":200}],
            "buildings": [],
            "actions": [{"actor_id":"10011","detail":"acceptTask","utility":10.0}],
            "execute_cmd": "cat /tmp/task.md",
            "task_stage": "execute",
            "deadline_remaining": 2.8,
            "learned_overlay": [{
                "path": "thresholds.prepare_margin_rounds",
                "base_value": 20.0,
                "relative_overlay": -0.05,
                "overlay_value": -1.0,
                "effective_value": 19.0,
            }],
        },
    )


def test_low_only_emits_minimal_round_block():
    logger, stream = _logger("v055.low")
    sink = LoggerTraceSink(logger=logger, mode="low")
    sink.emit(TraceEvent(kind="strategy_selected", round_id=9, data={"strategy_id":"x"}))
    sink.emit(_summary_event())
    text = stream.getvalue()
    assert "=====START=====" in text and "=====END=======" in text
    assert "Round 9" in text
    assert "Role 10011: acceptTask" in text
    assert "ExecCmd: cat /tmp/task.md" in text
    assert "Nodes:" not in text
    assert '"channel":"trace"' not in text
    assert "LearnedOverlay:" in text
    assert "thresholds.prepare_margin_rounds: -5.00%" in text
    assert text.index("LearnedOverlay:") < text.index("=====END=======")


def test_medium_emits_human_summary_but_no_structured_json():
    logger, stream = _logger("v055.medium")
    sink = LoggerTraceSink(logger=logger, mode="medium")
    sink.emit(TraceEvent(kind="strategy_selected", round_id=9, data={"strategy_id":"x"}))
    sink.emit(_summary_event())
    text = stream.getvalue()
    assert "Nodes: runtime_gate -> strategy -> candidates -> rank -> finalize" in text
    assert "[us] pioneer id=10011" in text
    assert '"channel":"trace"' not in text
    assert "LearnedOverlay:" in text
    assert "base=20.000, overlay=-1.000, effective=19.000" in text


def test_high_emits_human_summary_and_structured_trace():
    logger, stream = _logger("v055.high")
    sink = LoggerTraceSink(logger=logger, mode="high")
    sink.emit(TraceEvent(kind="strategy_selected", round_id=9, data={"strategy_id":"x"}))
    sink.emit(_summary_event())
    text = stream.getvalue()
    assert "=====START=====" in text
    assert '"channel":"trace"' in text
    assert "strategy_selected" in text


def test_structured_writer_is_silent_below_high():
    logger, stream = _logger("v055.writer")
    LoggerJsonWriter(channel="experience", logger=logger, mode="medium").write({"record_type":"x"})
    assert stream.getvalue() == ""
    LoggerJsonWriter(channel="experience", logger=logger, mode="high").write({"record_type":"x"})
    assert '"channel":"experience"' in stream.getvalue()
