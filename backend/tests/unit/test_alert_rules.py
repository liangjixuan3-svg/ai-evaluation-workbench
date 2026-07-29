from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.alerts.rules import AlertConfig, AlertMetrics, evaluate_alert_rules
from app.shared.enums import RootCause


def _metrics(
    *,
    failures: int,
    samples: int,
    scenario: str | None = "refund",
    root_cause: RootCause | None = RootCause.MISSING_KNOWLEDGE,
) -> AlertMetrics:
    return AlertMetrics(
        failures=failures,
        samples=samples,
        scenario=scenario,
        root_cause=root_cause,
        result_ids=("result-1", "result-2"),
        window_started_at=datetime(2026, 7, 29, tzinfo=UTC),
        window_ended_at=datetime(2026, 7, 30, tzinfo=UTC),
    )


def _config(**overrides: object) -> AlertConfig:
    values: dict[str, object] = {
        "min_samples": 30,
        "spike_delta": 0.15,
        "priority_scenarios": frozenset({"refund"}),
        "priority_scenario_failure_rate": 0.10,
        "overall_drop_delta": 0.08,
        "merge_window": timedelta(hours=6),
    }
    values.update(overrides)
    return AlertConfig(**values)


def test_issue_spike_is_primary_alert() -> None:
    signal = evaluate_alert_rules(
        window=_metrics(failures=28, samples=100),
        baseline=_metrics(failures=9, samples=100),
        config=_config(),
    )[0]

    assert signal.kind == "issue_spike"
    assert signal.priority == "P1"


def test_low_volume_fluctuation_does_not_alert() -> None:
    signals = evaluate_alert_rules(
        window=_metrics(failures=9, samples=10),
        baseline=_metrics(failures=0, samples=10),
        config=_config(),
    )

    assert signals == []


def test_priority_scenario_is_second_precedence_layer() -> None:
    signal = evaluate_alert_rules(
        window=_metrics(failures=12, samples=100),
        baseline=_metrics(failures=8, samples=100),
        config=_config(),
    )[0]

    assert signal.kind == "priority_scenario"
    assert signal.priority == "P2"


def test_overall_drop_is_guardrail_when_no_higher_layer_matches() -> None:
    signal = evaluate_alert_rules(
        window=_metrics(failures=18, samples=100, scenario=None, root_cause=None),
        baseline=_metrics(failures=9, samples=100, scenario=None, root_cause=None),
        config=_config(),
    )[0]

    assert signal.kind == "overall_drop"
    assert signal.priority == "P3"
