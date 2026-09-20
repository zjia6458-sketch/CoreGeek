from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import TypeVar

from .base import DomainEvent

E = TypeVar("E", bound=DomainEvent)
EventHandler = Callable[[DomainEvent], None]


class EventBus:
    """Synchronous in-process event bus.

    The bus deliberately contains no persistence or business logic.
    Trace/EventStore/analytics can subscribe independently.
    """

    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[EventHandler]] = defaultdict(list)

    def subscribe(
        self,
        event_type: type[E],
        handler: Callable[[E], None],
    ) -> None:
        self._handlers[event_type].append(handler)  # type: ignore[arg-type]

    def publish(self, event: DomainEvent) -> None:
        # Exact type subscribers first, then generic DomainEvent subscribers.
        handlers = tuple(self._handlers.get(type(event), ()))
        generic = tuple(self._handlers.get(DomainEvent, ()))

        for handler in handlers + generic:
            handler(event)
