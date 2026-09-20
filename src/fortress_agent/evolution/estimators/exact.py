from __future__ import annotations

from .base import (
    CounterfactualEstimate,
    CounterfactualEstimator,
)


class ExactSameActionEstimator(CounterfactualEstimator):
    estimator_id = "exact_same_action"
    priority = 10

    def supports(
        self,
        ctx,
        current,
        candidate,
    ) -> bool:
        return current.action == candidate.action

    def estimate(
        self,
        ctx,
        current,
        candidate,
        experiences,
    ):
        # Same physical action under the same context has identical
        # immediate environment effect. We still compare policy utility
        # because weights can differ.
        return CounterfactualEstimate(
            current_value=current.utility.total,
            candidate_value=candidate.utility.total,
            current_risk=current.utility.risk,
            candidate_risk=candidate.utility.risk,
            confidence=1.0,
            standard_error=0.0,
            method=self.estimator_id,
            comparable=True,
        )
