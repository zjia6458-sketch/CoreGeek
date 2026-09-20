from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import time
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class TraceEvent:
    kind: str
    round_id: int | None = None
    node_id: str | None = None
    message: str | None = None
    data: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
    correlation_id: str | None = None
    event_id: str | None = None
    timestamp_ns: int = field(default_factory=time.time_ns)


class TraceSink(ABC):
    """Trace 事件输出抽象类。

    生产实现：``observability/logger.py::LoggerTraceSink``，统一写入 main3.py
    配置的 root logger；本地测试/回放实现位于 ``observability/sinks.py``。
    Trace 只服务人类可观测性，绝不能反向驱动 Memory/Policy。
    """

    @abstractmethod
    def emit(self, event: TraceEvent) -> None:
        ...

    def close(self) -> None:
        pass
