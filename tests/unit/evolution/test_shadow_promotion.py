from fortress_agent.evolution.promotion import PromotionGate
from fortress_agent.evolution.shadow import (
    ShadowEvaluationRecord,
    ShadowReportBuilder,
)


def record(i, delta=2.0, risk=-0.1):
    return ShadowEvaluationRecord(
        decision_id=f"d{i}",
        current_policy_version=1,
        candidate_policy_version=2,
        current_action_type="move",
        candidate_action_type="move",
        current_value=1.0,
        candidate_value=1.0 + delta,
        delta_value=delta,
        delta_risk=risk,
        estimator_id="exact_same_action",
        confidence=1.0,
        standard_error=0.0,
        comparable=True,
    )


def test_positive_stable_candidate_can_pass_promotion_gate():
    records = tuple(
        record(i)
        for i in range(25)
    )

    report = ShadowReportBuilder().build(
        candidate_version=2,
        records=records,
        expected_contexts=25,
        candidate_latencies_ms=tuple(
            20.0 for _ in records
        ),
    )

    decision = PromotionGate(
        min_samples=20,
        max_risk_delta=0.0,
        min_context_coverage=0.8,
    ).evaluate(report)

    assert report.lcb_delta > 0
    assert decision.promote


def test_any_invalid_action_rejects_candidate():
    records = tuple(
        record(i)
        for i in range(25)
    )

    report = ShadowReportBuilder().build(
        candidate_version=2,
        records=records,
        invalid_count=1,
        expected_contexts=25,
    )

    decision = PromotionGate(
        min_samples=20,
    ).evaluate(report)

    assert not decision.promote
    assert "invalid" in decision.reason
