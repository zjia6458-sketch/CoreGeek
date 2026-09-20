from __future__ import annotations

from abc import ABC, abstractmethod
import json
from pathlib import Path

from .base import DomainEvent
from .serde import event_from_dict, event_to_dict


class EventStore(ABC):
    """DomainEvent 存储抽象类。

    生产内存实现：``InMemoryEventStore``；生产可观测包装：
    ``JournaledEventStore``；本地回放持久化实现：``JsonlEventStore``。
    Production 默认不会写 JSONL 文件，JournaledEventStore 通过 LoggerJsonWriter
    把事件投影到 main3.py 的唯一 root logger。
    """

    @abstractmethod
    def append(self, event: DomainEvent) -> None:
        ...

    @abstractmethod
    def all(self) -> tuple[DomainEvent, ...]:
        ...

    def after_round(self, round_id: int) -> tuple[DomainEvent, ...]:
        return tuple(event for event in self.all() if event.round_id > round_id)

    def since_round(self, round_id: int) -> tuple[DomainEvent, ...]:
        return tuple(event for event in self.all() if event.round_id >= round_id)


class InMemoryEventStore(EventStore):
    def __init__(self) -> None:
        self._events: list[DomainEvent] = []
        self._ids: set[str] = set()

    def append(self, event: DomainEvent) -> None:
        if event.event_id in self._ids:
            raise ValueError(f"duplicate event id: {event.event_id}")
        self._events.append(event)
        self._ids.add(event.event_id)

    def all(self) -> tuple[DomainEvent, ...]:
        return tuple(self._events)

    def __len__(self) -> int:
        return len(self._events)


class JsonlEventStore(EventStore):
    """Append-only persistent event store.

    This implementation favors correctness and inspectability. For the current
    game size (<= 1300 rounds), replaying a JSONL file is sufficiently cheap.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._ids: set[str] = set()

        if self._path.exists():
            for event in self.all():
                self._ids.add(event.event_id)

    def append(self, event: DomainEvent) -> None:
        if event.event_id in self._ids:
            raise ValueError(f"duplicate event id: {event.event_id}")

        self._path.parent.mkdir(parents=True, exist_ok=True)

        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    event_to_dict(event),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            handle.write("\n")

        self._ids.add(event.event_id)

    def all(self) -> tuple[DomainEvent, ...]:
        if not self._path.exists():
            return ()

        events: list[DomainEvent] = []

        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                events.append(event_from_dict(json.loads(line)))

        return tuple(events)


class JournaledEventStore(EventStore):
    """In-memory operational store + non-blocking persistent journal."""

    def __init__(self, inner: EventStore, writer) -> None:
        self._inner = inner
        self._writer = writer

    def append(self, event: DomainEvent) -> None:
        self._inner.append(event)
        self._writer.write(event_to_dict(event))

    def all(self) -> tuple[DomainEvent, ...]:
        return self._inner.all()

    def close(self) -> None:
        close = getattr(self._inner, 'close', None)
        if close is not None:
            close()
        self._writer.close()
