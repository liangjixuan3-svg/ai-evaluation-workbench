import pytest

from app.retest.service import InvalidRetestState, decide_retest


def test_retest_requires_both_cohorts_to_recover() -> None:
    outcome = decide_retest(
        replay_passed=9,
        replay_total=10,
        new_passed=7,
        new_total=10,
        threshold=0.8,
        min_replay=5,
        min_new=5,
    )

    assert outcome.recovered is False
    assert outcome.replay_pass_rate == 0.9
    assert outcome.new_sample_pass_rate == 0.7


def test_retest_rejects_insufficient_samples() -> None:
    with pytest.raises(InvalidRetestState, match="样本不足"):
        decide_retest(
            replay_passed=2,
            replay_total=2,
            new_passed=3,
            new_total=3,
            threshold=0.8,
            min_replay=5,
            min_new=5,
        )
