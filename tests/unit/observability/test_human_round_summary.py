import io
import logging

from fortress_agent.observability.logger import LoggerTraceSink
from fortress_agent.observability.trace import TraceEvent


def test_round_human_summary_contains_node_chain_and_economy_fields():
    stream = io.StringIO()
    logger = logging.getLogger("human-round-summary-test")
    logger.handlers.clear()
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    sink = LoggerTraceSink(logger=logger, mode="compact")
    sink.emit(TraceEvent(
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
        },
    ))
    text = stream.getvalue()
    assert "Round 9 (Day 1, DAY), Gold: 50, Score: 0" in text
    assert "Nodes: runtime_gate -> strategy -> candidates -> rank -> finalize" in text
    assert "Role 10011: acceptTask" in text
    assert "ExecCmd: cat /tmp/task.md" in text
