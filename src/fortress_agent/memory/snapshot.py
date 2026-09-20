from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from fortress_agent.memory.map import MapMemory
from fortress_agent.memory.resources import ResourceMemory, ResourceStatus
from fortress_agent.memory.world import WorldMemory


@dataclass(frozen=True, slots=True)
class WorldMemorySnapshot:
    round_id: int
    map_state: dict[str, Any]
    resource_state: list[dict[str, Any]]
    schema_version: int = 1


class WorldMemorySnapshotCodec:
    def dump(self, memory: WorldMemory, *, round_id: int) -> WorldMemorySnapshot:
        return WorldMemorySnapshot(
            round_id=round_id,
            map_state=memory.map.export_state(),
            resource_state=memory.resources.export_state(),
        )

    def restore(self, snapshot: WorldMemorySnapshot) -> WorldMemory:
        memory = WorldMemory()
        memory.map.import_state(snapshot.map_state)
        memory.resources.import_state(snapshot.resource_state)
        return memory


class JsonWorldMemorySnapshotStore:
    """Single latest snapshot with atomic replace."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def save(self, snapshot: WorldMemorySnapshot) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(asdict(snapshot), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        tmp.replace(self._path)

    def load(self) -> WorldMemorySnapshot | None:
        if not self._path.exists():
            return None

        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return WorldMemorySnapshot(
            round_id=int(raw["round_id"]),
            map_state=dict(raw["map_state"]),
            resource_state=list(raw["resource_state"]),
            schema_version=int(raw.get("schema_version", 1)),
        )
