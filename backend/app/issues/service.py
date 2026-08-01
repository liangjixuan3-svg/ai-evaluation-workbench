from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import Alert, AlertResult, Task
from app.analysis.models import BadcaseCluster, ClusterMember, RootCauseSuggestion
from app.evaluation.models import EvaluationResult
from app.ingestion.redaction import redact_conversation
from app.shared.enums import RootCause

IssueStatus = Literal["pending", "confirmed", "all"]


def list_issues(session: Session, status: IssueStatus) -> dict[str, Any]:
    clusters = list(
        session.scalars(
            select(BadcaseCluster).order_by(
                BadcaseCluster.created_at.desc(), BadcaseCluster.id.desc()
            )
        )
    )
    rows = [_cluster_row(session, cluster) for cluster in clusters]
    summary = {
        "pending_count": sum(row["status"] == "pending" for row in rows),
        "confirmed_count": sum(row["status"] == "confirmed" for row in rows),
        "impacted_count": sum(row["impact_count"] for row in rows),
        "missing_knowledge_count": sum(
            _displayed_root_cause(row) == RootCause.MISSING_KNOWLEDGE.value for row in rows
        ),
    }
    if status != "all":
        rows = [row for row in rows if row["status"] == status]
    rows.sort(
        key=lambda row: (
            row["status"] == "confirmed",
            -_priority_rank(row["priority"]),
        )
    )
    return {"summary": summary, "items": rows}


def issue_detail(session: Session, cluster_id: str) -> dict[str, Any]:
    cluster = session.get(BadcaseCluster, cluster_id)
    if cluster is None:
        raise LookupError("问题簇不存在")
    members = _members(session, cluster.id)
    row = _cluster_row(session, cluster, members)
    suggestion = _latest_suggestion(session, cluster.id)
    alert = _cluster_alert(session, members)
    task = session.scalar(
        select(Task)
        .where(Task.cluster_id == cluster.id)
        .order_by(Task.created_at.desc(), Task.id.desc())
    )
    return {
        **row,
        "alert": _alert_payload(alert),
        "suggestion": _suggestion_payload(suggestion),
        "confirmation": _confirmation_payload(members),
        "task": (
            {
                "id": task.id,
                "type": task.type.value,
                "status": task.status.value,
                "title": task.title,
            }
            if task
            else None
        ),
        "samples": [_sample_payload(session, member) for member in members[:3]],
    }


def _cluster_row(
    session: Session,
    cluster: BadcaseCluster,
    members: list[ClusterMember] | None = None,
) -> dict[str, Any]:
    members = members if members is not None else _members(session, cluster.id)
    suggestion = _latest_suggestion(session, cluster.id)
    alert = _cluster_alert(session, members)
    confirmed = bool(members) and all(member.confirmed_root_cause is not None for member in members)
    return {
        "id": cluster.id,
        "run_id": cluster.run_id,
        "scenario": cluster.scenario,
        "weakest_dimension": cluster.weakest_dimension,
        "problem_summary": cluster.normalized_reason,
        "impact_count": len(members),
        "priority": alert.priority if alert else "P2",
        "status": "confirmed" if confirmed else "pending",
        "suggestion": (
            {
                "root_cause": suggestion.root_cause.value,
                "confidence": suggestion.confidence.value,
            }
            if suggestion
            else None
        ),
        "created_at": cluster.created_at.isoformat(),
    }


def _members(session: Session, cluster_id: str) -> list[ClusterMember]:
    return list(
        session.scalars(
            select(ClusterMember)
            .where(ClusterMember.cluster_id == cluster_id)
            .order_by(
                ClusterMember.representative_rank.is_(None),
                ClusterMember.representative_rank,
                ClusterMember.evaluation_result_id,
            )
        )
    )


def _latest_suggestion(session: Session, cluster_id: str) -> RootCauseSuggestion | None:
    return session.scalar(
        select(RootCauseSuggestion)
        .where(RootCauseSuggestion.cluster_id == cluster_id)
        .order_by(RootCauseSuggestion.created_at.desc(), RootCauseSuggestion.id.desc())
    )


def _cluster_alert(session: Session, members: list[ClusterMember]) -> Alert | None:
    result_ids = [member.evaluation_result_id for member in members]
    if not result_ids:
        return None
    return session.scalar(
        select(Alert)
        .join(AlertResult, AlertResult.alert_id == Alert.id)
        .where(AlertResult.evaluation_result_id.in_(result_ids))
        .order_by(Alert.updated_at.desc(), Alert.id.desc())
    )


def _sample_payload(session: Session, member: ClusterMember) -> dict[str, Any]:
    result = session.get(EvaluationResult, member.evaluation_result_id)
    if result is None:
        raise LookupError("问题簇引用的评测结果不存在")
    conversation = redact_conversation(result.conversation)
    return {
        "result_id": result.id,
        "conversation_id": result.conversation_id,
        "external_id": conversation.external_id,
        "score": float(result.total_score),
        "dimensions": result.dimension_scores,
        "reason": result.reason,
        "evidence": result.evidence,
        "confidence": result.confidence.value,
        "messages": [
            {"role": message.role, "content": message.content}
            for message in conversation.messages
        ],
    }


def _suggestion_payload(suggestion: RootCauseSuggestion | None) -> dict[str, Any] | None:
    if suggestion is None:
        return None
    return {
        "id": suggestion.id,
        "root_cause": suggestion.root_cause.value,
        "reason": suggestion.reason,
        "evidence": suggestion.evidence,
        "confidence": suggestion.confidence.value,
        "provider": suggestion.provider,
        "model": suggestion.model,
    }


def _confirmation_payload(members: list[ClusterMember]) -> dict[str, Any] | None:
    if not members or any(member.confirmed_root_cause is None for member in members):
        return None
    causes = {member.confirmed_root_cause for member in members}
    actors = {member.confirmed_by for member in members}
    confirmed_times = [member.confirmed_at for member in members if member.confirmed_at is not None]
    return {
        "root_cause": next(iter(causes)).value if len(causes) == 1 else "mixed",
        "confirmed_by": next(iter(actors)) if len(actors) == 1 else "多人确认",
        "confirmed_at": max(confirmed_times).isoformat() if confirmed_times else None,
    }


def _alert_payload(alert: Alert | None) -> dict[str, Any] | None:
    if alert is None:
        return None
    return {
        "id": alert.id,
        "kind": alert.kind,
        "priority": alert.priority,
        "status": alert.status.value,
        "baseline_value": float(alert.baseline_value),
        "current_value": float(alert.current_value),
        "impact_count": alert.impact_count,
    }


def _displayed_root_cause(row: dict[str, Any]) -> str | None:
    suggestion = row["suggestion"]
    return suggestion["root_cause"] if suggestion else None


def _priority_rank(priority: str) -> int:
    return {"P1": 3, "P2": 2, "P3": 1}.get(priority, 0)
