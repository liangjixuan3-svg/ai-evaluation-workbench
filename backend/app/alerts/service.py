from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.alerts.models import Alert, AlertResult, AlertSignalReceipt
from app.alerts.rules import ALERT_PRECEDENCE, AlertSignal
from app.shared.enums import AlertStatus
from app.shared.types import new_uuid


def merge_alert(session: Session, signal: AlertSignal) -> Alert:
    """Merge a related open alert inside its configured window and retain all result links."""
    existing_receipt = session.get(AlertSignalReceipt, signal.fingerprint)
    if existing_receipt is not None:
        return _receipt_alert(session, existing_receipt)

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
    candidate = _new_alert(signal) if alert is None else None

    # Insert the receipt and a possible new alert in one savepoint before changing
    # impact, windows, or result links. A losing concurrent replay rolls back cleanly.
    try:
        with session.begin_nested():
            if candidate is not None:
                session.add(candidate)
                alert = candidate
            assert alert is not None
            session.add(AlertSignalReceipt(fingerprint=signal.fingerprint, alert_id=alert.id))
            session.flush()
    except IntegrityError:
        receipt = session.scalar(
            select(AlertSignalReceipt)
            .where(AlertSignalReceipt.fingerprint == signal.fingerprint)
            .with_for_update()
        )
        if receipt is None:
            session.rollback()
            raise
        alert = _receipt_alert(session, receipt)
        session.commit()
        return alert

    assert alert is not None
    if candidate is None:
        if ALERT_PRECEDENCE.get(signal.kind, float("inf")) < ALERT_PRECEDENCE.get(
            alert.kind, float("inf")
        ):
            alert.kind = signal.kind
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


def _new_alert(signal: AlertSignal) -> Alert:
    return Alert(
        id=new_uuid(),
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


def _receipt_alert(session: Session, receipt: AlertSignalReceipt) -> Alert:
    alert = session.get(Alert, receipt.alert_id)
    if alert is None:
        raise LookupError("alert signal receipt references a missing alert")
    return alert
