from enum import StrEnum


class AlertStatus(StrEnum):
    OPEN = "open"
    ANALYZING = "analyzing"
    AWAITING_FIX = "awaiting_fix"
    AWAITING_RETEST = "awaiting_retest"
    RECOVERED = "recovered"
    NOT_RECOVERED = "not_recovered"
    FALSE_POSITIVE = "false_positive"


class RootCause(StrEnum):
    MISSING_KNOWLEDGE = "missing_knowledge"
    MISUNDERSTANDING = "misunderstanding"
    PROCESS_FAILURE = "process_failure"
    SERVICE_TONE = "service_tone"
    OTHER = "other"


class TaskType(StrEnum):
    ATTRIBUTION_REVIEW = "attribution_review"
    QA_REVIEW = "qa_review"
    PROMPT_OPTIMIZATION = "prompt_optimization"
    PROCESS_INVESTIGATION = "process_investigation"
    TONE_OPTIMIZATION = "tone_optimization"
    EVALUATION_CALIBRATION = "evaluation_calibration"
    RETEST = "retest"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class QADraftStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    REGENERATION_REQUESTED = "regeneration_requested"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"


class TaskStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class JobStatus(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"


class RetestStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RECOVERED = "recovered"
    NOT_RECOVERED = "not_recovered"
    FAILED = "failed"


class RetestCohort(StrEnum):
    REPLAY = "replay"
    NEW = "new"
