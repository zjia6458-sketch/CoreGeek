from __future__ import annotations

from dataclasses import dataclass
import math

from fortress_agent.domain.decision import Decision
from fortress_agent.evolution.estimators.base import (
    CounterfactualEstimatorRegistry,
)
from fortress_agent.learning.experience.store import ExperienceStore
from fortress_agent.policy.context import PolicyContext


@dataclass(frozen=True, slots=True)
class ShadowEvaluationRecord:
    decision_id: str

    current_policy_version: int
    candidate_policy_version: int

    current_action_type: str
    candidate_action_type: str

    current_value: float
    candidate_value: float

    delta_value: float
    delta_risk: float

    estimator_id: str
    confidence: float
    standard_error: float

    comparable: bool


@dataclass(frozen=True, slots=True)
class ShadowReport:
    candidate_version: int

    comparable_samples: int

    mean_delta: float
    std_delta: float
    lcb_delta: float

    mean_risk_delta: float

    invalid_rate: float
    timeout_rate: float

    p95_latency_delta_ms: float
    p99_latency_ms: float

    context_coverage: float


class ShadowEvaluator:
    def __init__(
        self,
        estimators: CounterfactualEstimatorRegistry,
        experiences: ExperienceStore,
    ) -> None:
        self._estimators = estimators
        self._experiences = experiences

    def compare(
        self,
        *,
        decision_id: str,
        ctx: PolicyContext,
        current: Decision,
        candidate: Decision,
    ) -> ShadowEvaluationRecord:
        estimator = self._estimators.resolve(
            ctx,
            current,
            candidate,
        )

        estimate = estimator.estimate(
            ctx,
            current,
            candidate,
            self._experiences,
        )

        return ShadowEvaluationRecord(
            decision_id=decision_id,
            current_policy_version=ctx.policy_state.version,
            candidate_policy_version=candidate.policy_version,
            current_action_type=current.action.action_type,
            candidate_action_type=candidate.action.action_type,
            current_value=estimate.current_value,
            candidate_value=estimate.candidate_value,
            delta_value=(
                estimate.candidate_value
                - estimate.current_value
            ),
            delta_risk=(
                estimate.candidate_risk
                - estimate.current_risk
            ),
            estimator_id=estimate.method,
            confidence=estimate.confidence,
            standard_error=estimate.standard_error,
            comparable=estimate.comparable,
        )


class ShadowReportBuilder:
    def __init__(
        self,
        *,
        z_value: float = 1.96,
    ) -> None:
        self._z = z_value

    def build(
        self,
        *,
        candidate_version: int,
        records: tuple[ShadowEvaluationRecord, ...],
        invalid_count: int = 0,
        timeout_count: int = 0,
        latency_deltas_ms: tuple[float, ...] = (),
        candidate_latencies_ms: tuple[float, ...] = (),
        expected_contexts: int | None = None,
    ) -> ShadowReport:
        comparable = tuple(
            record
            for record in records
            if record.comparable
        )

        deltas = [
            record.delta_value
            for record in comparable
        ]
        risk_deltas = [
            record.delta_risk
            for record in comparable
        ]

        n = len(deltas)

        if n:
            mean_delta = sum(deltas) / n

            if n > 1:
                variance = sum(
                    (x - mean_delta) ** 2
                    for x in deltas
                ) / (n - 1)
                std_delta = math.sqrt(variance)
            else:
                std_delta = 0.0

            se = (
                std_delta / math.sqrt(n)
                if n > 1
                else max(
                    comparable[0].standard_error,
                    0.0,
                )
            )

            lcb = mean_delta - self._z * se
            mean_risk_delta = (
                sum(risk_deltas) / n
            )
        else:
            mean_delta = 0.0
            std_delta = 0.0
            lcb = float("-inf")
            mean_risk_delta = 0.0

        total = max(1, len(records))

        coverage = (
            min(
                1.0,
                n / expected_contexts,
            )
            if expected_contexts
            else (n / total)
        )

        return ShadowReport(
            candidate_version=candidate_version,
            comparable_samples=n,
            mean_delta=mean_delta,
            std_delta=std_delta,
            lcb_delta=lcb,
            mean_risk_delta=mean_risk_delta,
            invalid_rate=invalid_count / total,
            timeout_rate=timeout_count / total,
            p95_latency_delta_ms=self._percentile(
                latency_deltas_ms,
                0.95,
            ),
            p99_latency_ms=self._percentile(
                candidate_latencies_ms,
                0.99,
            ),
            context_coverage=coverage,
        )

    @staticmethod
    def _percentile(
        values: tuple[float, ...],
        q: float,
    ) -> float:
        if not values:
            return 0.0

        ordered = sorted(values)
        index = min(
            len(ordered) - 1,
            max(
                0,
                math.ceil(q * len(ordered)) - 1,
            ),
        )
        return ordered[index]
