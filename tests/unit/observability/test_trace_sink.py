import json

from fortress_agent.observability.sinks import (
    CompositeTraceSink,
    InMemoryTraceSink,
    QueueJsonlTraceSink,
)
from fortress_agent.observability.trace import TraceEvent


def test_composite_trace_sink_fans_out():
    a = InMemoryTraceSink()
    b = InMemoryTraceSink()
    sink = CompositeTraceSink(a, b)

    event = TraceEvent(kind="test", round_id=1)
    sink.emit(event)

    assert a.events == [event]
    assert b.events == [event]


def test_queue_jsonl_trace_sink_writes_structured_event(tmp_path):
    path = tmp_path / "trace.jsonl"
    sink = QueueJsonlTraceSink(path)

    sink.emit(
        TraceEvent(
            kind="policy_node_completed",
            round_id=7,
            node_id="rank",
            data={"outcome": "selected"},
        )
    )
    sink.close()

    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]

    assert rows[0]["kind"] == "policy_node_completed"
    assert rows[0]["node_id"] == "rank"
    assert rows[0]["data"]["outcome"] == "selected"
