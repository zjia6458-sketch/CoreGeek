from fortress_agent.events.store import JsonlEventStore
from fortress_agent.memory.recovery import WorldMemoryRecovery
from fortress_agent.memory.snapshot import (
    JsonWorldMemorySnapshotStore,
)
from fortress_agent.observation.memory_engine import WorldMemoryEngine
from fortress_agent.protocol.codec import GameProtocolCodec


def parse(payload):
    result = GameProtocolCodec().parse_state(payload)
    assert result.ok, result
    return result.value


def test_snapshot_roundtrip_and_event_recovery(tmp_path):
    event_path = tmp_path / "events.jsonl"
    snapshot_path = tmp_path / "world_snapshot.json"

    event_store = JsonlEventStore(event_path)
    engine = WorldMemoryEngine(event_store=event_store)

    engine.observe(parse({
        "round": 1,
        "day": 1,
        "phase": "day",
        "visible_cells": [{"x": 5, "y": 5, "terrain": "mine"}],
        "resources": [{
            "id": "iron-1",
            "type": "iron",
            "position": {"x": 5, "y": 5},
            "amount": 100,
        }],
    }))

    snapshot_store = JsonWorldMemorySnapshotStore(snapshot_path)
    engine.snapshot_to(snapshot_store, round_id=1)

    # Events after the snapshot.
    engine.observe(parse({
        "round": 2,
        "day": 1,
        "phase": "day",
        "visible_cells": [{"x": 5, "y": 5, "terrain": "mine"}],
        "resources": [],
    }))

    recovery = WorldMemoryRecovery(
        snapshot_store=snapshot_store,
        event_store=JsonlEventStore(event_path),
    )
    memory, last_round = recovery.recover()

    assert last_round == 2
    assert memory.map.cell(5, 5).discovered
    assert memory.resources.get("iron-1").status.value == "depleted"
