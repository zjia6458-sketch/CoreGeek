from __future__ import annotations

from fortress_agent.candidates.base import CandidateRegistry
from fortress_agent.policy.strategy import StrategyProfile


class CandidateService:
    def __init__(self, registry: CandidateRegistry) -> None:
        self._registry = registry

    def generate(
        self,
        ctx,
        strategy: StrategyProfile,
    ):
        return self._registry.generate_all(ctx, strategy)
