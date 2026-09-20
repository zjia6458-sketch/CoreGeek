from __future__ import annotations

from dataclasses import replace

from .reference import build_reference_strategy_selector


class BasicStrategySelector:
    """Backward-compatible facade over the StrategyGraph system.

    New production code uses ``build_reference_strategy_selector`` directly.
    The facade preserves a few historical strategy ids used by older tests and
    integrations while delegating all routing to StrategyGraph.
    """

    def __init__(self, **_: object) -> None:
        self._selector = build_reference_strategy_selector()

    def select(self, ctx):
        profile = self._selector.select(ctx)

        if profile.strategy_id == "economy":
            return replace(
                profile,
                strategy_id="gather",
            )

        return profile

    def explain(self, ctx):
        return self._selector.explain(ctx)
