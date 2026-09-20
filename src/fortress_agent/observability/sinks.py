from __future__ import annotations

import json
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Thread

from .trace import TraceEvent, TraceSink
from .journal import to_jsonable


class InMemoryTraceSink(TraceSink):
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def emit(self, event: TraceEvent) -> None:
        self.events.append(event)


class CompositeTraceSink(TraceSink):
    def __init__(self, *sinks: TraceSink) -> None:
        self._sinks = sinks

    def emit(self, event: TraceEvent) -> None:
        for sink in self._sinks:
            sink.emit(event)

    def close(self) -> None:
        for sink in self._sinks:
            sink.close()


class QueueJsonlTraceSink(TraceSink):
    """Non-blocking decision-path trace sink.

    ``emit`` uses ``put_nowait``. If the logging queue is full, trace records
    are dropped instead of blocking the policy deadline.
    """

    _STOP = object()

    def __init__(
        self,
        path: str | Path,
        *,
        max_queue_size: int = 10_000,
    ) -> None:
        self._path = Path(path)
        self._queue: Queue[TraceEvent | object] = Queue(maxsize=max_queue_size)
        self._closed = False
        self.dropped_events = 0

        self._thread = Thread(
            target=self._run,
            name="fortress-trace-writer",
            daemon=True,
        )
        self._thread.start()

    def emit(self, event: TraceEvent) -> None:
        if self._closed:
            return

        try:
            self._queue.put_nowait(event)
        except Full:
            self.dropped_events += 1

    def close(self) -> None:
        if self._closed:
            return

        self._closed = True
        self._queue.put(self._STOP)
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

        with self._path.open("a", encoding="utf-8") as handle:
            while True:
                item = self._queue.get()

                if item is self._STOP:
                    break

                event = item
                assert isinstance(event, TraceEvent)

                payload = to_jsonable(event)

                handle.write(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                handle.write("\n")
                handle.flush()
