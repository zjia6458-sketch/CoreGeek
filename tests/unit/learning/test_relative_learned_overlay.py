from fortress_agent.domain.policy_state import PolicyPatch, PolicyState
from fortress_agent.learning.policy_repository import InMemoryPolicyStateRepository


def test_learned_overlay_is_relative_to_base_and_scales_when_base_changes():
    initial = PolicyState.create(
        thresholds={"example": 4.0},
        utility_weights={"economy": 1.0},
    )
    repo = InMemoryPolicyStateRepository(initial)
    patch = PolicyPatch(
        patch_id="p1",
        parent_version=1,
        component="thresholds",
        key="example",
        old_value=4.0,
        new_value=4.2,
        reason="learn +0.2 from base 4",
        proposer="test",
        confidence=1.0,
    )
    candidate = repo.create_candidate(patch)

    assert round(candidate.overlay_ratio("thresholds", "example"), 6) == 0.05
    assert round(candidate.thresholds["example"], 6) == 4.2
    row = candidate.overlay_snapshot()[0]
    assert row["base_value"] == 4.0
    assert round(float(row["overlay_value"]), 6) == 0.2

    rebased = candidate.rebase(thresholds={"example": 8.0})
    assert round(rebased.overlay_ratio("thresholds", "example"), 6) == 0.05
    assert round(rebased.thresholds["example"], 6) == 8.4
    rebased_row = rebased.overlay_snapshot()[0]
    assert rebased_row["base_value"] == 8.0
    assert round(float(rebased_row["overlay_value"]), 6) == 0.4


def test_repository_accumulates_relative_overlay_against_fixed_base():
    initial = PolicyState.create(utility_weights={"economy": 1.0})
    repo = InMemoryPolicyStateRepository(initial)

    c1 = repo.create_candidate(PolicyPatch(
        patch_id="p1", parent_version=1,
        component="utility_weights", key="economy",
        old_value=1.0, new_value=1.05,
        reason="step1", proposer="test", confidence=1.0,
    ))
    repo.promote(c1.version)
    assert round(c1.overlay_ratio("utility_weights", "economy"), 6) == 0.05

    c2 = repo.create_candidate(PolicyPatch(
        patch_id="p2", parent_version=c1.version,
        component="utility_weights", key="economy",
        old_value=1.05, new_value=1.10,
        reason="step2", proposer="test", confidence=1.0,
    ))
    assert round(c2.overlay_ratio("utility_weights", "economy"), 6) == 0.10
    assert round(c2.utility_weights["economy"], 6) == 1.10


def test_zero_base_rejects_relative_overlay_learning():
    initial = PolicyState.create(parameters={"zero": 0.0})
    repo = InMemoryPolicyStateRepository(initial)
    patch = PolicyPatch(
        patch_id="p0", parent_version=1,
        component="parameters", key="zero",
        old_value=0.0, new_value=0.1,
        reason="undefined relative scale", proposer="test", confidence=1.0,
    )
    try:
        repo.create_candidate(patch)
    except ValueError as exc:
        assert "non-zero base" in str(exc)
    else:
        raise AssertionError("zero base must not accept relative overlay")
