from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.alerts.models import Task
from app.analysis.models import BadcaseCluster, ClusterMember, RootCauseSuggestion
from app.evaluation.contracts import ProviderAttribution, QADraftContent, QADraftRequest
from app.evaluation.models import EvaluationResult
from app.evaluation.providers import EvaluationProvider
from app.ingestion.redaction import redact_conversation
from app.remediation.models import QADraft, QAEvidence, QAVersion
from app.shared.audit import record_audit
from app.shared.enums import Confidence, QADraftStatus, RootCause, TaskType
from app.shared.types import utc_now

ROOT_CAUSE_TASK = {
    RootCause.MISSING_KNOWLEDGE: TaskType.QA_REVIEW,
    RootCause.MISUNDERSTANDING: TaskType.PROMPT_OPTIMIZATION,
    RootCause.PROCESS_FAILURE: TaskType.PROCESS_INVESTIGATION,
    RootCause.SERVICE_TONE: TaskType.TONE_OPTIMIZATION,
    RootCause.OTHER: TaskType.EVALUATION_CALIBRATION,
}


class AttributionConfirmationError(ValueError):
    pass


class BulkConfirmationNotAllowed(AttributionConfirmationError):
    pass


class IncompleteAttribution(AttributionConfirmationError):
    pass


class InvalidAttributionRoute(AttributionConfirmationError):
    pass


class MissingBusinessEvidence(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AttributionCommand:
    cluster_id: str
    actor: str
    root_cause: RootCause
    member_ids: tuple[str, ...]
    evidence: tuple[str, ...]
    bulk: bool = False
    confirm_cluster: bool = False


def confirm_attribution(session: Session, command: AttributionCommand) -> Task | None:
    """Record human decisions without changing the original AI attribution."""
    cluster = session.get(BadcaseCluster, command.cluster_id)
    if cluster is None:
        raise LookupError(f"badcase cluster {command.cluster_id} does not exist")
    if not command.actor.strip():
        raise AttributionConfirmationError("actor and human confirmation evidence are required")
    evidence = _validated_confirmation_evidence(command.evidence)
    members = list(
        session.scalars(
            select(ClusterMember)
            .where(ClusterMember.cluster_id == command.cluster_id)
            .order_by(ClusterMember.evaluation_result_id)
            .with_for_update()
        )
    )
    if not members:
        raise IncompleteAttribution("badcase cluster has no members")
    confidence = _cluster_confidence(session, command.cluster_id)
    selected_members = _members_to_confirm(members, command, confidence)
    now = utc_now()
    for member in selected_members:
        member.confirmed_root_cause = command.root_cause
        member.confirmed_by = command.actor
        member.confirmed_at = now
    record_audit(
        session,
        actor=command.actor,
        action="attribution_confirmed",
        entity_type="badcase_cluster",
        entity_id=command.cluster_id,
        payload={
            "evidence": list(evidence),
            "root_cause": command.root_cause.value,
            "member_ids": [member.evaluation_result_id for member in selected_members],
            "bulk": command.bulk,
        },
    )
    if not all(member.confirmed_root_cause is not None for member in members):
        session.commit()
        return None
    tasks = _route_confirmed_members(session, cluster, members, command.actor, evidence)
    session.commit()
    return tasks.get(command.root_cause)


def generate_qa_draft(session: Session, cluster_id: str, provider: EvaluationProvider) -> QADraft:
    """Generate one provider-validated QA draft for a fully confirmed knowledge gap."""
    if not isinstance(provider, EvaluationProvider):
        raise TypeError("provider must be a validated EvaluationProvider")
    cluster = session.get(BadcaseCluster, cluster_id)
    if cluster is None:
        raise LookupError(f"badcase cluster {cluster_id} does not exist")
    members = list(
        session.scalars(
            select(ClusterMember)
            .where(ClusterMember.cluster_id == cluster_id)
            .order_by(
                ClusterMember.representative_rank.is_(None), ClusterMember.representative_rank
            )
            .with_for_update()
        )
    )
    if not members or any(
        member.confirmed_root_cause != RootCause.MISSING_KNOWLEDGE for member in members
    ):
        raise IncompleteAttribution("QA drafts require every member confirmed as missing_knowledge")
    task = session.scalar(
        select(Task)
        .where(Task.cluster_id == cluster_id, Task.type == TaskType.QA_REVIEW)
        .with_for_update()
    )
    if task is None:
        raise InvalidAttributionRoute("missing_knowledge remediation task does not exist")
    existing = session.scalar(select(QADraft).where(QADraft.task_id == task.id).with_for_update())
    if existing is not None:
        return existing
    representative_member, representative, suggestion = _representative_attribution(
        session, cluster_id, members
    )
    confirmed_root_cause = representative_member.confirmed_root_cause
    assert confirmed_root_cause is not None
    if suggestion is None:
        attribution_reason = representative.reason
        attribution_evidence = representative.evidence
        attribution_confidence = representative.confidence
    else:
        attribution_reason = suggestion.reason
        attribution_evidence = suggestion.evidence
        attribution_confidence = suggestion.confidence
    response = provider.draft_qa(
        QADraftRequest(
            conversation=redact_conversation(representative.conversation),
            attribution=ProviderAttribution(
                root_cause=confirmed_root_cause,
                reason=attribution_reason,
                evidence=attribution_evidence,
                confidence=_provider_confidence(attribution_confidence),
            ),
        )
    )
    draft = QADraft(
        cluster_id=cluster_id,
        task_id=task.id,
        status=QADraftStatus.PENDING_REVIEW,
        current_version_number=1,
        confidence=_stored_confidence(response.confidence),
    )
    version = QAVersion(
        draft=draft,
        version_number=1,
        content=response.content.model_dump(),
        created_by=f"{provider.identity.provider}:{provider.identity.model}",
    )
    try:
        with session.begin_nested():
            session.add_all((draft, version))
            session.flush()
            _add_generation_evidence(
                session, version, response.evidence, suggestion, representative
            )
            record_audit(
                session,
                actor=f"{provider.identity.provider}:{provider.identity.model}",
                action="qa_draft_generated",
                entity_type="qa_draft",
                entity_id=draft.id,
                payload={
                    "evidence": list(response.evidence),
                    "cluster_id": cluster_id,
                    "version_number": 1,
                    "confirmed_root_cause": confirmed_root_cause.value,
                    "ai_suggestion_id": suggestion.id if suggestion is not None else None,
                    "ai_root_cause": (
                        suggestion.root_cause.value if suggestion is not None else None
                    ),
                },
            )
    except IntegrityError:
        existing = session.scalar(
            select(QADraft).where(QADraft.task_id == task.id).with_for_update()
        )
        if existing is None:
            raise
        return existing
    session.commit()
    return draft


def approve_qa(
    session: Session, draft_id: str, actor: str, edits: Mapping[str, Any] | None
) -> QAVersion:
    """Approve by appending a new immutable version, never changing a prior version."""
    draft = session.scalar(select(QADraft).where(QADraft.id == draft_id).with_for_update())
    if draft is None:
        raise LookupError(f"QA draft {draft_id} does not exist")
    if not actor.strip():
        raise ValueError("actor is required")
    update = dict(edits or {})
    business_evidence = update.pop("business_evidence", [])
    if not isinstance(business_evidence, list) or not business_evidence:
        raise MissingBusinessEvidence("business evidence is required before approval")
    validated_evidence = _validated_business_evidence(business_evidence)
    previous = session.scalar(
        select(QAVersion)
        .where(
            QAVersion.draft_id == draft.id,
            QAVersion.version_number == draft.current_version_number,
        )
        .with_for_update()
    )
    if previous is None:
        raise LookupError("QA draft current version does not exist")
    content = dict(previous.content)
    content.update(update)
    validated_content = QADraftContent.model_validate(content)
    version = QAVersion(
        draft=draft,
        version_number=draft.current_version_number + 1,
        content=validated_content.model_dump(),
        created_by=actor,
        approved_by=actor,
        approved_at=utc_now(),
    )
    session.add(version)
    with session.begin_nested():
        session.flush()
        _add_business_evidence(session, version, validated_evidence)
        draft.current_version_number = version.version_number
        draft.status = QADraftStatus.APPROVED
        record_audit(
            session,
            actor=actor,
            action="qa_approved",
            entity_type="qa_version",
            entity_id=version.id,
            payload={
                "evidence": business_evidence,
                "draft_id": draft.id,
                "version_number": version.version_number,
                "edited_fields": sorted(update),
            },
        )
    session.commit()
    return version


def _cluster_confidence(session: Session, cluster_id: str) -> Confidence:
    confidence = session.scalar(
        select(RootCauseSuggestion.confidence)
        .where(RootCauseSuggestion.cluster_id == cluster_id)
        .order_by(RootCauseSuggestion.created_at.desc(), RootCauseSuggestion.id.desc())
    )
    if confidence is None:
        raise IncompleteAttribution("an AI attribution suggestion is required before confirmation")
    return confidence


def _members_to_confirm(
    members: list[ClusterMember], command: AttributionCommand, confidence: Confidence
) -> list[ClusterMember]:
    if command.bulk and command.confirm_cluster:
        raise AttributionConfirmationError("bulk and confirm_cluster cannot both be true")
    if command.confirm_cluster:
        if any(
            member.confirmed_root_cause not in (None, command.root_cause) for member in members
        ):
            raise AttributionConfirmationError("已确认的归因不能被其他原因覆盖")
        return [member for member in members if member.confirmed_root_cause is None]
    if command.bulk:
        if confidence != Confidence.HIGH:
            raise BulkConfirmationNotAllowed("only high-confidence clusters may be bulk confirmed")
        return members
    selected = set(command.member_ids)
    if len(selected) != 1:
        raise AttributionConfirmationError("individual confirmation requires exactly one member")
    selected_members = [member for member in members if member.evaluation_result_id in selected]
    if len(selected_members) != 1:
        raise AttributionConfirmationError("selected member does not belong to the cluster")
    return selected_members


def _validated_confirmation_evidence(evidence: tuple[str, ...]) -> tuple[str, ...]:
    if not evidence:
        raise AttributionConfirmationError("actor and human confirmation evidence are required")
    if any(not isinstance(item, str) or not item.strip() for item in evidence):
        raise AttributionConfirmationError("human confirmation evidence entries must not be blank")
    return tuple(item.strip() for item in evidence)


def _route_confirmed_members(
    session: Session,
    cluster: BadcaseCluster,
    members: Iterable[ClusterMember],
    actor: str,
    evidence: tuple[str, ...],
) -> dict[RootCause, Task]:
    root_causes = {member.confirmed_root_cause for member in members}
    if None in root_causes:
        raise IncompleteAttribution("all cluster members must be human-confirmed")
    tasks: dict[RootCause, Task] = {}
    for root_cause in sorted(root_causes, key=lambda value: value.value):
        assert root_cause is not None
        task_type = ROOT_CAUSE_TASK[root_cause]
        task = session.scalar(
            select(Task)
            .where(Task.cluster_id == cluster.id, Task.type == task_type)
            .with_for_update()
        )
        if task is None:
            task = Task(
                type=task_type,
                cluster_id=cluster.id,
                title=f"{root_cause.value} remediation for {cluster.id}",
                priority="P2",
                payload={"root_cause": root_cause.value, "evidence": list(evidence)},
            )
            session.add(task)
            session.flush()
            record_audit(
                session,
                actor=actor,
                action="remediation_task_routed",
                entity_type="task",
                entity_id=task.id,
                payload={"evidence": list(evidence), "root_cause": root_cause.value},
            )
        tasks[root_cause] = task
    return tasks


def _representative_attribution(
    session: Session, cluster_id: str, members: list[ClusterMember]
) -> tuple[ClusterMember, EvaluationResult, RootCauseSuggestion | None]:
    fallback: tuple[ClusterMember, EvaluationResult] | None = None
    for member in members:
        result = session.get(EvaluationResult, member.evaluation_result_id)
        if result is None:
            raise LookupError("cluster member references a missing evaluation result")
        if fallback is None:
            fallback = (member, result)
        suggestion = session.scalar(
            select(RootCauseSuggestion)
            .where(
                RootCauseSuggestion.cluster_id == cluster_id,
                RootCauseSuggestion.evaluation_result_id == result.id,
            )
            .order_by(RootCauseSuggestion.created_at.desc(), RootCauseSuggestion.id.desc())
        )
        if suggestion is not None:
            return member, result, suggestion
    assert fallback is not None
    return fallback[0], fallback[1], None


def _add_generation_evidence(
    session: Session,
    version: QAVersion,
    provider_evidence: list[str],
    suggestion: RootCauseSuggestion | None,
    representative: EvaluationResult,
) -> None:
    session.add_all(
        QAEvidence(
            qa_version_id=version.id,
            source_type="conversation",
            source_ref=f"conversation:{representative.conversation_id}",
            excerpt=excerpt,
            conversation_id=representative.conversation_id,
            evaluation_result_id=representative.id,
        )
        for excerpt in provider_evidence
    )
    if suggestion is not None:
        session.add_all(
            QAEvidence(
                qa_version_id=version.id,
                source_type="ai_attribution",
                source_ref=f"root_cause_suggestion:{suggestion.id}",
                excerpt=excerpt,
                evaluation_result_id=suggestion.evaluation_result_id,
            )
            for excerpt in suggestion.evidence
        )
        return
    session.add_all(
        QAEvidence(
            qa_version_id=version.id,
            source_type="confirmed_evaluation",
            source_ref=f"evaluation_result:{representative.id}",
            excerpt=excerpt,
            conversation_id=representative.conversation_id,
            evaluation_result_id=representative.id,
        )
        for excerpt in representative.evidence
    )


def _validated_business_evidence(evidence: list[Any]) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    for item in evidence:
        if not isinstance(item, Mapping):
            raise MissingBusinessEvidence("business evidence entries must be objects")
        source_ref = item.get("source_ref")
        excerpt = item.get("excerpt")
        if not isinstance(source_ref, str) or not source_ref.strip():
            raise MissingBusinessEvidence("business evidence source_ref is required")
        if not isinstance(excerpt, str) or not excerpt.strip():
            raise MissingBusinessEvidence("business evidence excerpt is required")
        records.append((source_ref.strip(), excerpt.strip()))
    return records


def _add_business_evidence(
    session: Session, version: QAVersion, evidence: list[tuple[str, str]]
) -> None:
    session.add_all(
        (
            QAEvidence(
                qa_version_id=version.id,
                source_type="business_reference",
                source_ref=source_ref,
                excerpt=excerpt,
            )
            for source_ref, excerpt in evidence
        )
    )


def _provider_confidence(confidence: Confidence) -> float:
    return {Confidence.HIGH: 0.9, Confidence.MEDIUM: 0.6, Confidence.LOW: 0.3}[confidence]


def _stored_confidence(confidence: float) -> Confidence:
    if confidence >= 0.8:
        return Confidence.HIGH
    if confidence >= 0.5:
        return Confidence.MEDIUM
    return Confidence.LOW
