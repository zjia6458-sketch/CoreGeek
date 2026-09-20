from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
import json
from pathlib import Path
from queue import Full, Queue
from threading import Thread
from typing import Mapping


def to_jsonable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            field.name: to_jsonable(
                getattr(value, field.name)
            )
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {
            str(key): to_jsonable(item)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list, set, frozenset)):
        return [to_jsonable(item) for item in value]
    return repr(value)


class QueueJsonlWriter:
    """Non-blocking generic JSONL writer for runtime journals."""

    _STOP = object()

    def __init__(
        self,
        path: str | Path,
        *,
        max_queue_size: int = 10_000,
    ) -> None:
        self.path = Path(path)
        self._queue: Queue[dict | object] = Queue(maxsize=max_queue_size)
        self._closed = False
        self.dropped_records = 0
        self._thread = Thread(
            target=self._run,
            name=f'jsonl:{self.path.name}',
            daemon=True,
        )
        self._thread.start()

    def write(self, payload: Mapping[str, object]) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait(dict(payload))
        except Full:
            self.dropped_records += 1

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._queue.put(self._STOP)
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as handle:
            while True:
                item = self._queue.get()
                if item is self._STOP:
                    break
                payload = to_jsonable(item)
                handle.write(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
                handle.write('\n')
                handle.flush()
