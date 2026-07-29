from uuid import UUID

from app.ingestion.contracts import SampleCandidate
from app.ingestion.sampling import SamplingPolicy, select_sample


def test_sampling_is_reproducible() -> None:
    items = [
        SampleCandidate(UUID("00000000-0000-0000-0000-000000000001"), "normal", False),
        SampleCandidate(UUID("00000000-0000-0000-0000-000000000002"), "priority", False),
        SampleCandidate(UUID("00000000-0000-0000-0000-000000000003"), "normal", True),
    ]
    policy = SamplingPolicy(3, 1 / 3, 1 / 3, 1 / 3, frozenset({"priority"}))

    assert select_sample(items, policy, seed=42) == select_sample(items, policy, seed=42)


def test_sampling_prioritizes_risk_then_scenarios_without_duplicate_ids() -> None:
    risk_id = UUID("00000000-0000-0000-0000-000000000001")
    scenario_id = UUID("00000000-0000-0000-0000-000000000002")
    random_id = UUID("00000000-0000-0000-0000-000000000003")
    items = [
        SampleCandidate(risk_id, "priority", True),
        SampleCandidate(risk_id, "priority", False),
        SampleCandidate(scenario_id, "priority", False),
        SampleCandidate(random_id, "normal", False),
    ]
    policy = SamplingPolicy(2, 0, 0.5, 0.5, frozenset({"priority"}))

    selected = select_sample(items, policy, seed=7)

    assert selected == [risk_id, scenario_id]
    assert len(selected) == len(set(selected))
    assert len(selected) <= policy.daily_budget


def test_sampling_assigns_a_fractional_slot_to_risk_before_lower_buckets() -> None:
    risk_id = UUID("00000000-0000-0000-0000-000000000001")
    scenario_id = UUID("00000000-0000-0000-0000-000000000002")
    random_id = UUID("00000000-0000-0000-0000-000000000003")
    items = [
        SampleCandidate(risk_id, "priority", True),
        SampleCandidate(scenario_id, "priority", False),
        SampleCandidate(random_id, "normal", False),
    ]
    policy = SamplingPolicy(1, 1 / 3, 1 / 3, 1 / 3, frozenset({"priority"}))

    assert select_sample(items, policy, seed=7) == [risk_id]


def test_sampling_never_exceeds_budget_when_ratios_sum_to_more_than_one() -> None:
    risk_id = UUID("00000000-0000-0000-0000-000000000001")
    scenario_id = UUID("00000000-0000-0000-0000-000000000002")
    random_id = UUID("00000000-0000-0000-0000-000000000003")
    items = [
        SampleCandidate(risk_id, "priority", True),
        SampleCandidate(scenario_id, "priority", False),
        SampleCandidate(random_id, "normal", False),
    ]
    policy = SamplingPolicy(1, 1, 1, 1, frozenset({"priority"}))

    assert select_sample(items, policy, seed=7) == [risk_id]
