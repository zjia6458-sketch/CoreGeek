from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

EntityId = str | int


class ResourceStatus(str, Enum):
    UNKNOWN = "unknown"
    AVAILABLE = "available"
    DEPLETED = "depleted"
    STALE = "stale"


@dataclass(slots=True)
class _ResourceNodeMemory:
    resource_id: EntityId
    resource_type: str
    x: int
    y: int
    status: ResourceStatus
    last_known_amount: int | None
    first_seen_round: int
    last_seen_round: int
    depleted_round: int | None = None


@dataclass(frozen=True, slots=True)
class ResourceNodeMemoryView:
    resource_id: EntityId
    resource_type: str
    x: int
    y: int
    status: ResourceStatus
    last_known_amount: int | None
    first_seen_round: int
    last_seen_round: int
    depleted_round: int | None


class ResourceMemory:
    def __init__(self) -> None:
        self._nodes: dict[EntityId, _ResourceNodeMemory] = {}

    def get(self, resource_id: EntityId) -> ResourceNodeMemoryView | None:
        node = self._nodes.get(resource_id)
        return self._view(node) if node is not None else None

    def discover(
        self,
        *,
        resource_id: EntityId,
        resource_type: str,
        x: int,
        y: int,
        amount: int | None,
        round_id: int,
    ) -> None:
        self._nodes[resource_id] = _ResourceNodeMemory(
            resource_id=resource_id,
            resource_type=resource_type,
            x=x,
            y=y,
            status=ResourceStatus.AVAILABLE,
            last_known_amount=amount,
            first_seen_round=round_id,
            last_seen_round=round_id,
        )

    def update(
        self,
        *,
        resource_id: EntityId,
        amount: int | None,
        round_id: int,
    ) -> None:
        node = self._nodes[resource_id]
        node.last_known_amount = amount
        node.last_seen_round = round_id
        node.status = ResourceStatus.AVAILABLE
        node.depleted_round = None

    def deplete(self, *, resource_id: EntityId, round_id: int) -> None:
        node = self._nodes[resource_id]
        node.status = ResourceStatus.DEPLETED
        node.last_known_amount = 0
        node.last_seen_round = round_id
        node.depleted_round = round_id

    def replenish(
        self,
        *,
        resource_id: EntityId,
        resource_type: str,
        x: int,
        y: int,
        amount: int | None,
        round_id: int,
    ) -> None:
        node = self._nodes.get(resource_id)

        if node is None:
            self.discover(
                resource_id=resource_id,
                resource_type=resource_type,
                x=x,
                y=y,
                amount=amount,
                round_id=round_id,
            )
            return

        node.resource_type = resource_type
        node.x = x
        node.y = y
        node.status = ResourceStatus.AVAILABLE
        node.last_known_amount = amount
        node.last_seen_round = round_id
        node.depleted_round = None

    def all(self) -> tuple[ResourceNodeMemoryView, ...]:
        return tuple(
            self._view(node)
            for _, node in sorted(self._nodes.items(), key=lambda item: str(item[0]))
        )

    def available(
        self,
        resource_type: str | None = None,
    ) -> tuple[ResourceNodeMemoryView, ...]:
        return tuple(
            node
            for node in self.all()
            if node.status is ResourceStatus.AVAILABLE
            and (resource_type is None or node.resource_type == resource_type)
        )


    def export_state(self) -> list[dict[str, object]]:
        return [
            {
                "resource_id": node.resource_id,
                "resource_type": node.resource_type,
                "x": node.x,
                "y": node.y,
                "status": node.status.value,
                "last_known_amount": node.last_known_amount,
                "first_seen_round": node.first_seen_round,
                "last_seen_round": node.last_seen_round,
                "depleted_round": node.depleted_round,
            }
            for node in self.all()
        ]

    def import_state(self, rows: list[dict[str, object]]) -> None:
        self._nodes.clear()

        for row in rows:
            resource_id = row["resource_id"]
            self._nodes[resource_id] = _ResourceNodeMemory(
                resource_id=resource_id,
                resource_type=str(row["resource_type"]),
                x=int(row["x"]),
                y=int(row["y"]),
                status=ResourceStatus(str(row["status"])),
                last_known_amount=(
                    None
                    if row.get("last_known_amount") is None
                    else int(row["last_known_amount"])
                ),
                first_seen_round=int(row["first_seen_round"]),
                last_seen_round=int(row["last_seen_round"]),
                depleted_round=(
                    None
                    if row.get("depleted_round") is None
                    else int(row["depleted_round"])
                ),
            )

    @staticmethod
    def _view(node: _ResourceNodeMemory) -> ResourceNodeMemoryView:
        return ResourceNodeMemoryView(
            resource_id=node.resource_id,
            resource_type=node.resource_type,
            x=node.x,
            y=node.y,
            status=node.status,
            last_known_amount=node.last_known_amount,
            first_seen_round=node.first_seen_round,
            last_seen_round=node.last_seen_round,
            depleted_round=node.depleted_round,
        )


class ResourceMemoryView:
    def __init__(self, memory: ResourceMemory) -> None:
        self._memory = memory

    def get(self, resource_id: EntityId) -> ResourceNodeMemoryView | None:
        return self._memory.get(resource_id)

    def all(self) -> tuple[ResourceNodeMemoryView, ...]:
        return self._memory.all()

    def available(
        self,
        resource_type: str | None = None,
    ) -> tuple[ResourceNodeMemoryView, ...]:
        return self._memory.available(resource_type)
