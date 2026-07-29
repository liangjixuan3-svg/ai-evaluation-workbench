from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.shared.enums import RootCause

ALERT_PRECEDENCE = {"issue_spike": 0, "priority_scenario": 1, "overall_drop": 2}


@dataclass(frozen=True, slots=True)
class AlertConfig:
    min_samples: int
    spike_delta: float
    priority_scenarios: frozenset[str]
    priority_scenario_failure_rate: float
    overall_drop_delta: float
    merge_window: timedelta


@dataclass(frozen=True, slots=True)
class AlertMetrics:
    failures: int
    samples: int
    scenario: str | None
    root_cause: RootCause | None
    result_ids: tuple[str, ...]
    window_started_at: datetime
    window_ended_at: datetime

    @property
    def failure_rate(self) -> float:
        return self.failures / self.samples if self.samples else 0.0


@dataclass(frozen=True, slots=True)
class AlertSignal:
    kind: str
    priority: str
    scenario: str | None
    root_cause: RootCause | None
    baseline_value: float
    current_value: float
    impact_count: int
    result_ids: tuple[str, ...]
    window_started_at: datetime
    window_ended_at: datetime
    merge_window: timedelta

    @property
    def merge_key(self) -> str:
        scenario = self.scenario or "all-scenarios"
        root_cause = self.root_cause.value if self.root_cause else "unattributed"
        return f"{scenario}:{root_cause}"


def alert_config(**values: object) -> AlertConfig:
    return AlertConfig(**values)  # type: ignore[arg-type]


def metrics(**values: object) -> AlertMetrics:
    return AlertMetrics(**values)  # type: ignore[arg-type]


def evaluate_alert_rules(
    window: AlertMetrics, baseline: AlertMetrics, config: AlertConfig
) -> list[AlertSignal]:
    """Return only the highest-precedence rule that is supported by enough data."""
    if window.samples < config.min_samples or baseline.samples < config.min_samples:
        return []
    delta = window.failure_rate - baseline.failure_rate
    if delta >= config.spike_delta:
        return [_signal("issue_spike", "P1", window, baseline, config)]
    if (
        window.scenario in config.priority_scenarios
        and window.failure_rate >= config.priority_scenario_failure_rate
    ):
        return [_signal("priority_scenario", "P2", window, baseline, config)]
    if delta >= config.overall_drop_delta:
        return [_signal("overall_drop", "P3", window, baseline, config)]
    return []


def _signal(
    kind: str, priority: str, window: AlertMetrics, baseline: AlertMetrics, config: AlertConfig
) -> AlertSignal:
    return AlertSignal(
        kind=kind,
        priority=priority,
        scenario=window.scenario,
        root_cause=window.root_cause,
        baseline_value=baseline.failure_rate,
        current_value=window.failure_rate,
        impact_count=window.failures,
        result_ids=window.result_ids,
        window_started_at=window.window_started_at,
        window_ended_at=window.window_ended_at,
        merge_window=config.merge_window,
    )
