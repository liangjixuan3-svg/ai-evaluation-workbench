from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evaluation.models import EvaluationResult, EvaluationRun, RuleVersion
from app.ingestion.models import Conversation
from app.ingestion.redaction import redact_text
from app.retest.models import RetestRun, RetestSample
from app.retest.service import retest_method_run, retest_workspace_detail
from app.shared.enums import RetestCohort


def retest_detail(session: Session, run_id: str) -> dict[str, Any]:
    summary = retest_workspace_detail(session, run_id)
    run = session.get(RetestRun, run_id)
    if run is None:
        raise LookupError("复测任务不存在")
    method_run = retest_method_run(session, run)
    rule = session.get(RuleVersion, run.rule_version_id)
    samples = _sample_details(session, run_id)
    explanation = _explain(summary, samples)
    return {
        **summary,
        "method": _method(summary, method_run, rule),
        "explanation": explanation,
        "samples": samples,
    }


def _sample_details(session: Session, run_id: str) -> list[dict[str, Any]]:
    samples = list(
        session.scalars(
            select(RetestSample).where(RetestSample.retest_run_id == run_id)
        )
    )
    details = []
    for sample in samples:
        conversation = session.get(Conversation, sample.conversation_id)
        result = (
            session.get(EvaluationResult, sample.retest_evaluation_result_id)
            if sample.retest_evaluation_result_id
            else None
        )
        if conversation is None:
            continue
        details.append(
            {
                "id": f"{sample.retest_run_id}:{sample.conversation_id}:{sample.cohort.value}",
                "cohort": sample.cohort.value,
                "status": "completed" if result else "pending",
                "external_id": conversation.external_id,
                "scenario": conversation.scenario,
                "occurred_at": conversation.occurred_at.isoformat(),
                "conversation": {"messages": _messages(conversation.body)},
                "evaluation": _evaluation(result),
            }
        )
    return sorted(details, key=_sample_sort_key)


def _messages(body: dict[str, Any]) -> list[dict[str, str]]:
    raw_messages = body.get("messages", [])
    if not isinstance(raw_messages, list):
        return []
    messages = []
    for message in raw_messages:
        if not isinstance(message, dict):
            continue
        messages.append(
            {
                "role": str(message.get("role", "unknown")),
                "content": redact_text(str(message.get("content", ""))),
            }
        )
    return messages


def _evaluation(result: EvaluationResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "total_score": float(result.total_score),
        "dimension_scores": dict(result.dimension_scores),
        "passed": result.passed,
        "reason": result.reason,
        "evidence": list(result.evidence),
        "confidence": result.confidence.value,
        "severe_factual_error": result.severe_factual_error,
        "severe_compliance_error": result.severe_compliance_error,
    }


def _sample_sort_key(item: dict[str, Any]) -> tuple[int, float, str]:
    evaluation = item["evaluation"]
    if evaluation is None:
        return (1, 0, item["occurred_at"])
    if not evaluation["passed"]:
        return (0, evaluation["total_score"], item["occurred_at"])
    return (2, evaluation["total_score"], item["occurred_at"])


def _cohort_stats(samples: list[dict[str, Any]], cohort: RetestCohort) -> dict[str, Any]:
    selected = [sample for sample in samples if sample["cohort"] == cohort.value]
    completed = [sample for sample in selected if sample["evaluation"] is not None]
    passed = sum(sample["evaluation"]["passed"] for sample in completed)
    return {
        "passed": passed,
        "completed": len(completed),
        "total": len(selected),
        "pass_rate": passed / len(completed) if completed else None,
    }


def _explain(summary: dict[str, Any], samples: list[dict[str, Any]]) -> dict[str, Any]:
    replay = _cohort_stats(samples, RetestCohort.REPLAY)
    fresh = _cohort_stats(samples, RetestCohort.NEW)
    state = summary["workspace_state"]
    if summary["new_samples"]["available"] < summary["new_samples"]["required"]:
        verdict = "等待发布后新对话样本"
    elif summary["replay_samples"]["available"] < summary["replay_samples"]["required"]:
        verdict = "等待历史回放样本"
    elif state == "recovered":
        verdict = "两组通过率均达标，改善有效"
    elif state == "not_recovered":
        verdict = "至少一组通过率未达标，仍需改进"
    elif replay["completed"] + fresh["completed"]:
        verdict = "复测尚未完成，可继续处理剩余样本"
    else:
        verdict = "样本已就绪，等待开始复测"
    return {
        "verdict": verdict,
        "formula": "历史回放和新对话两组通过率都达标",
        "replay": replay,
        "new": fresh,
    }


def _method(
    summary: dict[str, Any], source_run: EvaluationRun | None, rule: RuleVersion | None
) -> dict[str, Any]:
    quality_version = source_run.quality_standard_version if source_run else None
    return {
        "sample_selection": {
            "replay": "关联问题中的历史失败对话",
            "new": "QA 发布后的同场景新对话",
        },
        "quality_standard": (
            {
                "name": quality_version.standard.name,
                "version": f"V{quality_version.version_number}",
                "rules": quality_version.rules,
            }
            if quality_version
            else None
        ),
        "prompt": (
            {
                "name": source_run.prompt_version.name,
                "version": source_run.prompt_version.version,
                "content": source_run.prompt_version.content,
            }
            if source_run
            else None
        ),
        "model": source_run.model if source_run else "",
        "template": (
            {
                "name": source_run.template.name,
                "version": source_run.template.version,
                "weights": source_run.template.weights,
            }
            if source_run
            else None
        ),
        "single_score_threshold": summary["locked_rule"]["threshold"],
        "cohort_pass_rate_threshold": summary["locked_rule"]["pass_rate_threshold"],
        "retest_rule": {"version": rule.version, "config": rule.config} if rule else None,
    }
