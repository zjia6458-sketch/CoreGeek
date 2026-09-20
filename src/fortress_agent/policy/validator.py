from __future__ import annotations

from fortress_agent.policy.legal import BasicLegalActionFilter


class BasicValidationService:
    def __init__(
        self,
        legal_filter: BasicLegalActionFilter,
    ) -> None:
        self._legal = legal_filter

    def valid(self, ctx, action) -> bool:
        return self._legal.is_legal(ctx, action)
