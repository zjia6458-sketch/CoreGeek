from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from fortress_agent.domain.decision import Decision
from fortress_agent.learning.experience.store import ExperienceStore
from fortress_agent.policy.context import PolicyContext


@dataclass(frozen=True, slots=True)
class CounterfactualEstimate:
    current_value: float
    candidate_value: float
    current_risk: float
    candidate_risk: float

    confidence: float
    standard_error: float

    method: str
    comparable: bool = True


class CounterfactualEstimator(ABC):
    estimator_id: str
    priority: int = 100

    @abstractmethod
    def supports(
        self,
        ctx: PolicyContext,
        current: Decision,
        candidate: Decision,
    ) -> bool:
        ...

    @abstractmethod
    def estimate(
        self,
        ctx: PolicyContext,
        current: Decision,
        candidate: Decision,
        experiences: ExperienceStore,
    ) -> CounterfactualEstimate:
        ...


class CounterfactualEstimatorRegistry:
    def __init__(self) -> None:
        self._estimators = []

    def register(
        self,
        estimator: CounterfactualEstimator,
    ) -> None:
        if any(
            x.estimator_id == estimator.estimator_id
            for x in self._estimators
        ):
            raise ValueError(
                f"duplicate estimator: {estimator.estimator_id}"
            )
        self._estimators.append(estimator)
        self._estimators.sort(
            key=lambda x: (
                x.priority,
                x.estimator_id,
            )
        )

    def resolve(
        self,
        ctx: PolicyContext,
        current: Decision,
        candidate: Decision,
    ) -> CounterfactualEstimator:
        for estimator in self._estimators:
            if estimator.supports(
                ctx,
                current,
                candidate,
            ):
                return estimator

        raise LookupError(
            "no counterfactual estimator supports comparison"
        )
