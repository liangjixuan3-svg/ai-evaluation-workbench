from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analysis.models import BadcaseCluster, ClusterMember, RootCauseSuggestion
from app.evaluation.contracts import AttributionRequest, ProviderEvaluation
from app.evaluation.models import EvaluationResult
from app.evaluation.providers import EvaluationProvider
from app.ingestion.redaction import redact_conversation
from app.shared.enums import Confidence

GROUPING_ALGORITHM_VERSION = "badcase-grouping-v1"
_CONFIDENCE_RANK = {Confidence.HIGH: 0, Confidence.MEDIUM: 1, Confidence.LOW: 2}


@dataclass(frozen=True, slots=True)
class ClusterDraft:
    run_id: str
    scenario: str | None
    weakest_dimension: str
    normalized_reason: str
    algorithm_version: str
    member_ids: tuple[str, ...]
    representative_ids: tuple[str, ...]


def normalize_reason(reason: str) -> str:
    """Return the stable v1 text component of a badcase grouping key."""
    normalized = unicodedata.normalize("NFKC", reason).casefold()
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return " ".join(normalized.split())


def cluster_badcases(results: Iterable[EvaluationResult]) -> list[ClusterDraft]:
    """Group failed immutable results by the v1 key and select up to three samples."""
    groups: dict[tuple[str | None, str, str], list[EvaluationResult]] = {}
    for result in results:
        if result.passed:
            continue
        weakest_dimension = _weakest_dimension(result)
        key = (
            result.conversation.scenario,
            weakest_dimension,
            normalize_reason(result.reason),
        )
        groups.setdefault(key, []).append(result)

    drafts: list[ClusterDraft] = []
    for (scenario, weakest_dimension, normalized_reason), members in sorted(
        groups.items(), key=lambda item: (item[0][0] or "", item[0][1], item[0][2])
    ):
        ordered_members = _ordered_members(members)
        drafts.append(
            ClusterDraft(
                run_id=ordered_members[0].run_id,
                scenario=scenario,
                weakest_dimension=weakest_dimension,
                normalized_reason=normalized_reason,
                algorithm_version=GROUPING_ALGORITHM_VERSION,
                member_ids=tuple(member.id for member in ordered_members),
                representative_ids=tuple(member.id for member in ordered_members[:3]),
            )
        )
    return drafts


def persist_clusters(session: Session, drafts: Iterable[ClusterDraft]) -> list[BadcaseCluster]:
    """Persist every member link while marking only selected samples as representatives."""
    clusters: list[BadcaseCluster] = []
    for draft in drafts:
        grouping_key = _cluster_grouping_key(draft)
        cluster = session.scalar(
            select(BadcaseCluster)
            .where(BadcaseCluster.grouping_key == grouping_key)
            .with_for_update()
        )
        if cluster is None:
            candidate = BadcaseCluster(
                run_id=draft.run_id,
                scenario=draft.scenario,
                weakest_dimension=draft.weakest_dimension,
                normalized_reason=draft.normalized_reason,
                algorithm_version=draft.algorithm_version,
                grouping_key=grouping_key,
            )
            try:
                with session.begin_nested():
                    session.add(candidate)
                    session.flush()
                cluster = candidate
            except IntegrityError:
                cluster = session.scalar(
                    select(BadcaseCluster)
                    .where(BadcaseCluster.grouping_key == grouping_key)
                    .with_for_update()
                )
                if cluster is None:
                    raise
        representative_rank = {
            result_id: rank for rank, result_id in enumerate(draft.representative_ids, start=1)
        }
        existing_member_ids = set(
            session.scalars(
                select(ClusterMember.evaluation_result_id).where(
                    ClusterMember.cluster_id == cluster.id
                )
            )
        )
        session.add_all(
            ClusterMember(
                cluster_id=cluster.id,
                evaluation_result_id=result_id,
                representative_rank=representative_rank.get(result_id),
            )
            for result_id in draft.member_ids
            if result_id not in existing_member_ids
        )
        clusters.append(cluster)
    session.commit()
    return clusters


def attribute_cluster(
    session: Session, cluster_id: str, provider: EvaluationProvider
) -> RootCauseSuggestion:
    """Ask the validated provider for a suggestion without confirming a human attribution."""
    if not isinstance(provider, EvaluationProvider):
        raise TypeError("provider must be a validated EvaluationProvider")
    cluster = session.get(BadcaseCluster, cluster_id)
    if cluster is None:
        raise LookupError(f"badcase cluster {cluster_id} does not exist")
    result = session.scalar(
        select(EvaluationResult)
        .join(ClusterMember, ClusterMember.evaluation_result_id == EvaluationResult.id)
        .where(ClusterMember.cluster_id == cluster_id)
        .order_by(ClusterMember.representative_rank.is_(None), ClusterMember.representative_rank)
    )
    if result is None:
        raise ValueError("badcase cluster has no evaluation results")

    identity = provider.identity
    existing_suggestion = session.scalar(
        select(RootCauseSuggestion)
        .where(
            RootCauseSuggestion.cluster_id == cluster.id,
            RootCauseSuggestion.evaluation_result_id == result.id,
            RootCauseSuggestion.provider == identity.provider,
            RootCauseSuggestion.model == identity.model,
        )
        .with_for_update()
    )
    if existing_suggestion is not None:
        return existing_suggestion

    evaluation = ProviderEvaluation(
        dimensions=result.dimension_scores,
        reason=result.reason,
        evidence=result.evidence,
        confidence=_provider_confidence(result.confidence),
        severe_factual_error=result.severe_factual_error,
        severe_compliance_error=result.severe_compliance_error,
    )
    response = provider.attribute(
        AttributionRequest(
            conversation=redact_conversation(result.conversation),
            evaluation=evaluation,
        )
    )
    suggestion = RootCauseSuggestion(
        cluster_id=cluster.id,
        evaluation_result_id=result.id,
        provider=identity.provider,
        model=identity.model,
        root_cause=response.root_cause,
        reason=response.reason,
        evidence=response.evidence,
        confidence=_stored_confidence(response.confidence),
    )
    try:
        with session.begin_nested():
            session.add(suggestion)
            session.flush()
    except IntegrityError:
        suggestion = session.scalar(
            select(RootCauseSuggestion)
            .where(
                RootCauseSuggestion.cluster_id == cluster.id,
                RootCauseSuggestion.evaluation_result_id == result.id,
                RootCauseSuggestion.provider == identity.provider,
                RootCauseSuggestion.model == identity.model,
            )
            .with_for_update()
        )
        if suggestion is None:
            raise
    session.commit()
    return suggestion


def _weakest_dimension(result: EvaluationResult) -> str:
    if not result.dimension_scores:
        raise ValueError("failed evaluation result must include dimension scores")
    return min(
        result.dimension_scores, key=lambda name: (float(result.dimension_scores[name]), name)
    )


def _ordered_members(members: Iterable[EvaluationResult]) -> list[EvaluationResult]:
    return sorted(
        members,
        key=lambda item: (
            _CONFIDENCE_RANK[item.confidence],
            item.created_at,
            item.id,
        ),
    )


def _provider_confidence(confidence: Confidence) -> float:
    return {Confidence.HIGH: 0.9, Confidence.MEDIUM: 0.6, Confidence.LOW: 0.3}[confidence]


def _stored_confidence(confidence: float) -> Confidence:
    if confidence >= 0.8:
        return Confidence.HIGH
    if confidence >= 0.5:
        return Confidence.MEDIUM
    return Confidence.LOW


def _cluster_grouping_key(draft: ClusterDraft) -> str:
    payload = [
        draft.scenario,
        draft.weakest_dimension,
        draft.normalized_reason,
    ]
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()
