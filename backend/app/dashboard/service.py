from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.models import Alert, Task
from app.evaluation.models import EvaluationResult, EvaluationRun
from app.remediation.models import QADraft
from app.retest.models import RetestRun
from app.shared.audit import AuditEvent
from app.shared.enums import AlertStatus, QADraftStatus, RetestStatus, TaskStatus, TaskType

ACTIVE_ALERTS = (
    AlertStatus.OPEN,
    AlertStatus.ANALYZING,
    AlertStatus.AWAITING_FIX,
    AlertStatus.AWAITING_RETEST,
    AlertStatus.NOT_RECOVERED,
)


def get_workbench_summary(session: Session) -> dict[str, Any]:
    results = list(session.scalars(select(EvaluationResult).order_by(EvaluationResult.created_at)))
    pass_rate = sum(result.passed for result in results) / len(results) if results else 0.0
    alerts = list(
        session.scalars(
            select(Alert)
            .where(Alert.status.in_(ACTIVE_ALERTS))
            .order_by(Alert.priority, Alert.impact_count.desc(), Alert.created_at)
            .limit(12)
        )
    )
    tasks = list(
        session.scalars(
            select(Task)
            .where(Task.status.in_((TaskStatus.OPEN, TaskStatus.IN_PROGRESS)))
            .order_by(Task.priority, Task.created_at)
            .limit(20)
        )
    )
    task_counts = Counter(task.type for task in tasks)
    pending_qa = session.scalar(
        select(func.count())
        .select_from(QADraft)
        .where(QADraft.status == QADraftStatus.PENDING_REVIEW)
    )
    pending_retests = session.scalar(
        select(func.count())
        .select_from(RetestRun)
        .where(RetestRun.status.in_((RetestStatus.QUEUED, RetestStatus.RUNNING)))
    )
    items = [_alert_item(alert) for alert in alerts]
    alert_ids = {alert.id for alert in alerts}
    items.extend(_task_item(task) for task in tasks if task.alert_id not in alert_ids)
    items.sort(
        key=lambda item: (
            item["priority"],
            -int(item["impact_count"]),
            item["created_at"],
        )
    )
    activities = list(
        session.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(8))
    )
    runs = list(
        session.scalars(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(5))
    )
    return {
        "pass_rate": round(pass_rate, 4),
        "pass_rate_delta": 0.0,
        "alerts": [
            {
                "id": alert.id,
                "kind": alert.kind,
                "priority": alert.priority,
                "scenario": alert.scenario,
                "root_cause": alert.root_cause.value if alert.root_cause else None,
                "status": alert.status.value,
                "impact_count": alert.impact_count,
            }
            for alert in alerts
        ],
        "counts": {
            "new_alerts": len(alerts),
            "pending_attributions": task_counts[TaskType.ATTRIBUTION_REVIEW],
            "pending_qa": int(pending_qa or 0),
            "pending_retests": int(pending_retests or 0),
        },
        "priority_items": items[:12],
        "recent_activity": [
            {
                "id": event.id,
                "action": event.action,
                "actor": event.actor,
                "created_at": event.created_at.isoformat(),
            }
            for event in activities
        ],
        "recent_runs": [
            {
                "id": run.id,
                "status": run.status.value,
                "succeeded_count": run.succeeded_count,
                "failed_count": run.failed_count,
                "created_at": run.created_at.isoformat(),
            }
            for run in runs
        ],
    }


def _alert_item(alert: Alert) -> dict[str, Any]:
    if alert.status == AlertStatus.AWAITING_RETEST:
        label, path = "查看复测进度", f"/retests?alert={alert.id}"
    elif alert.root_cause is None:
        label, path = "查看样本并确认归因", f"/alerts/{alert.id}"
    else:
        label, path = "推进改进方案", f"/alerts/{alert.id}"
    return {
        "id": f"alert:{alert.id}",
        "kind": "alert",
        "title": f"{alert.scenario or '未知场景'} · {alert.kind}",
        "description": f"通过率 {float(alert.current_value):.0%}，影响 {alert.impact_count} 条对话",
        "priority": alert.priority,
        "status": alert.status.value,
        "impact_count": alert.impact_count,
        "created_at": alert.created_at.isoformat(),
        "next_action": {"label": label, "method": "GET", "path": path},
    }


def _task_item(task: Task) -> dict[str, Any]:
    action = {
        TaskType.ATTRIBUTION_REVIEW: "确认问题原因",
        TaskType.QA_REVIEW: "审核 QA 草稿",
        TaskType.RETEST: "查看复测结果",
    }.get(task.type, "处理改进任务")
    return {
        "id": f"task:{task.id}",
        "kind": "task",
        "title": task.title,
        "description": "系统已整理证据，等待人工决策",
        "priority": task.priority,
        "status": task.status.value,
        "impact_count": int(task.payload.get("impact_count", 0)),
        "created_at": task.created_at.isoformat(),
        "next_action": {"label": action, "method": "GET", "path": f"/tasks/{task.id}"},
    }
