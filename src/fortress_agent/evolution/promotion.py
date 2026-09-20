from __future__ import annotations

from dataclasses import dataclass

from .shadow import ShadowReport


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    promote: bool
    reason: str


class PromotionGate:
    def __init__(
        self,
        *,
        min_samples: int = 20,
        max_risk_delta: float = 0.0,
        min_context_coverage: float = 0.8,
        max_p99_latency_ms: float = 2000.0,
    ) -> None:
        self.min_samples = min_samples
        self.max_risk_delta = max_risk_delta
        self.min_context_coverage = min_context_coverage
        self.max_p99_latency_ms = max_p99_latency_ms

    def evaluate(
        self,
        report: ShadowReport,
    ) -> PromotionDecision:
        if report.invalid_rate > 0:
            return PromotionDecision(
                False,
                "candidate produced invalid actions",
            )

        if report.timeout_rate > 0:
            return PromotionDecision(
                False,
                "candidate timed out",
            )

        if (
            report.comparable_samples
            < self.min_samples
        ):
            return PromotionDecision(
                False,
                "insufficient comparable samples",
            )

        if (
            report.context_coverage
            < self.min_context_coverage
        ):
            return PromotionDecision(
                False,
                "insufficient context coverage",
            )

        if (
            report.mean_risk_delta
            > self.max_risk_delta
        ):
            return PromotionDecision(
                False,
                "candidate increases risk beyond limit",
            )

        if (
            report.p99_latency_ms
            > self.max_p99_latency_ms
        ):
            return PromotionDecision(
                False,
                "candidate latency exceeds budget",
            )

        if report.lcb_delta <= 0:
            return PromotionDecision(
                False,
                "lower confidence bound is not positive",
            )

        return PromotionDecision(
            True,
            "candidate passed all promotion gates",
        )
