from __future__ import annotations

from .base import (
    CounterfactualEstimate,
    CounterfactualEstimator,
)


class DirectUtilityEstimator(CounterfactualEstimator):
    """Fallback Direct Method using each policy's own utility estimate.

    This is deliberately lower-confidence than exact/simulator/history methods.
    """

    estimator_id = "direct_utility"
    priority = 100

    def supports(
        self,
        ctx,
        current,
        candidate,
    ) -> bool:
        return True

    def estimate(
        self,
        ctx,
        current,
        candidate,
        experiences,
    ):
        spread = abs(
            candidate.utility.total
            - current.utility.total
        )

        return CounterfactualEstimate(
            current_value=current.utility.total,
            candidate_value=candidate.utility.total,
            current_risk=current.utility.risk,
            candidate_risk=candidate.utility.risk,
            confidence=0.35,
            standard_error=max(
                0.5,
                spread * 0.25,
            ),
            method=self.estimator_id,
            comparable=True,
        )
