from __future__ import annotations

import time
from typing import Protocol


class DeadlineExceeded(RuntimeError):
    """单回合内部预算已经不足，调用方应立即降级而不是继续计算。

    这个异常只表示**本地决策预算**耗尽，不等同于判题器返回的 TIMEOUT。
    Runtime 捕获它后会生成合法的空响应，从而给 HTTP 序列化、写 socket 等
    收尾动作预留时间。
    """

    def __init__(self, stage: str, remaining: float) -> None:
        self.stage = stage
        self.remaining_seconds = max(0.0, float(remaining))
        super().__init__(
            f"deadline budget exhausted at {stage}: "
            f"remaining={self.remaining_seconds:.6f}s"
        )


class DeadlineView(Protocol):
    """只读截止时间接口。

    主要实现：:class:`Deadline`。
    主要使用方：PolicyGraph、Candidate、Pathfinder、RuntimeGuard。
    """

    def remaining(self) -> float:
        ...

    def expired(self) -> bool:
        ...

    def ensure_remaining(
        self,
        minimum_seconds: float,
        *,
        stage: str,
    ) -> None:
        ...


class Deadline:
    """基于 ``time.monotonic`` 的单回合内部时间预算。

    注意这里的 timeout 并不是服务器协议的 5 秒，而是比 5 秒更短的内部预算。
    差值用于 JSON 序列化、线程调度、TCP 写回以及判题器侧的网络抖动。
    """

    def __init__(self, timeout_seconds: float) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        self._start = time.monotonic()
        self._end = self._start + timeout_seconds

    def elapsed(self) -> float:
        return max(0.0, time.monotonic() - self._start)

    def remaining(self) -> float:
        return max(0.0, self._end - time.monotonic())

    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def ensure_remaining(
        self,
        minimum_seconds: float,
        *,
        stage: str,
    ) -> None:
        """确保还保留指定预算，否则抛出 :class:`DeadlineExceeded`。

        ``minimum_seconds`` 是“从现在开始还必须至少剩多少秒”，而不是该阶段
        最多允许执行多少秒。这样下游始终能留有统一的 response reserve。
        """

        remaining = self.remaining()
        if remaining < max(0.0, minimum_seconds):
            raise DeadlineExceeded(stage, remaining)
