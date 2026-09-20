from __future__ import annotations

from fortress_agent.policy.context import PolicyContext


class BasicRuntimeModeResolver:
    def __init__(
        self,
        *,
        fast_threshold: float = 2.5,
        safe_threshold: float = 1.5,
        emergency_threshold: float = 0.6,
    ) -> None:
        self.fast_threshold = fast_threshold
        self.safe_threshold = safe_threshold
        self.emergency_threshold = emergency_threshold

    def mode(self, ctx: PolicyContext) -> str:
        remaining = ctx.deadline.remaining()

        if remaining < self.emergency_threshold:
            return "EMERGENCY"
        if remaining < self.safe_threshold:
            return "SAFE"
        if remaining < self.fast_threshold:
            return "FAST"
        return "FULL"
