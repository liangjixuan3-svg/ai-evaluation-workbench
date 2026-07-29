from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import Alert, AlertResult
from app.alerts.rules import AlertSignal
from app.shared.enums import AlertStatus


def merge_alert(session: Session, signal: AlertSignal) -> Alert:
    """Merge a related open alert inside its configured window and retain all result links."""
    earliest_end = signal.window_started_at - signal.merge_window
    alert = session.scalar(
        select(Alert)
        .where(
            Alert.status == AlertStatus.OPEN,
            Alert.merge_key == signal.merge_key,
            Alert.window_ended_at >= earliest_end,
        )
        .order_by(Alert.window_ended_at.desc(), Alert.created_at.desc())
        .with_for_update()
    )
    if alert is None:
        alert = Alert(
            kind=signal.kind,
            priority=signal.priority,
            scenario=signal.scenario,
            root_cause=signal.root_cause,
            merge_key=signal.merge_key,
            baseline_value=Decimal(str(signal.baseline_value)),
            current_value=Decimal(str(signal.current_value)),
            impact_count=0,
            window_started_at=signal.window_started_at,
            window_ended_at=signal.window_ended_at,
        )
        session.add(alert)
        session.flush()
    else:
        alert.priority = signal.priority
        alert.baseline_value = Decimal(str(signal.baseline_value))
        alert.current_value = Decimal(str(signal.current_value))
        alert.window_started_at = min(alert.window_started_at, signal.window_started_at)
        alert.window_ended_at = max(alert.window_ended_at, signal.window_ended_at)

    existing_ids = set(
        session.scalars(
            select(AlertResult.evaluation_result_id).where(AlertResult.alert_id == alert.id)
        )
    )
    new_ids = [
        result_id for result_id in dict.fromkeys(signal.result_ids) if result_id not in existing_ids
    ]
    session.add_all(
        AlertResult(alert_id=alert.id, evaluation_result_id=result_id) for result_id in new_ids
    )
    alert.impact_count += len(new_ids) or (signal.impact_count if not existing_ids else 0)
    session.commit()
    return alert
