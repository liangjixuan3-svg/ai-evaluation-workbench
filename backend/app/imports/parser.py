from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.imports.contracts import (
    ArrayCandidate,
    ImportMapping,
    NormalizationError,
    NormalizationResult,
)
from app.ingestion.contracts import ConversationInput

MAX_RECORDS = 10_000
MAX_DEPTH = 8
ID_NAMES = ("conversation_id", "conversationId", "session_id", "sessionId", "id")
TIME_NAMES = (
    "occurred_at",
    "occurredAt",
    "created_at",
    "createdAt",
    "timestamp",
    "time",
)
SCENARIO_NAMES = ("scenario", "scene", "intent", "category")
STATUS_NAMES = ("status", "state", "result")
MESSAGE_NAMES = ("messages", "turns", "records")
QUESTION_NAMES = ("question", "query", "user_question", "userMessage")
ANSWER_NAMES = ("answer", "response", "assistant_answer", "botMessage")
ROLE_NAMES = ("role", "speaker", "sender", "author")
CONTENT_NAMES = ("content", "text", "message", "body")


def discover_record_arrays(document: Any, max_depth: int = MAX_DEPTH) -> list[ArrayCandidate]:
    candidates: list[ArrayCandidate] = []
    _walk_arrays(document, "$", 0, max_depth, candidates)
    return sorted(
        candidates,
        key=lambda item: (-item.object_ratio, item.path.count("."), -item.length, item.path),
    )


def suggest_mapping(records: tuple[dict[str, object], ...]) -> ImportMapping:
    if not records:
        raise ValueError("需要至少一条对象记录才能推荐字段")
    record = records[0]
    occurred_at_path = _first_key(record, TIME_NAMES)
    if occurred_at_path is None:
        occurred_at_path = ""
    messages_path = _first_list_key(record, MESSAGE_NAMES)
    if messages_path is not None:
        messages = record[messages_path]
        first_message = next((item for item in messages if isinstance(item, dict)), {})
        return ImportMapping(
            record_path="$",
            id_path=_first_key(record, ID_NAMES),
            occurred_at_path=occurred_at_path,
            scenario_path=_first_key(record, SCENARIO_NAMES),
            status_path=_first_key(record, STATUS_NAMES),
            message_mode="messages",
            messages_path=messages_path,
            role_path=_first_key(first_message, ROLE_NAMES) or "role",
            content_path=_first_key(first_message, CONTENT_NAMES) or "content",
        )
    return ImportMapping(
        record_path="$",
        id_path=_first_key(record, ID_NAMES),
        occurred_at_path=occurred_at_path,
        scenario_path=_first_key(record, SCENARIO_NAMES),
        status_path=_first_key(record, STATUS_NAMES),
        message_mode="qa_pair",
        question_path=_first_key(record, QUESTION_NAMES) or "question",
        answer_path=_first_key(record, ANSWER_NAMES) or "answer",
    )


def read_record_array(document: Any, path: str) -> list[Any]:
    records = _read_path(document, path)
    if not isinstance(records, list):
        raise TypeError("映射的记录路径不是数组")
    return records


def normalize_records(
    document: Any,
    mapping: ImportMapping,
    timezone_name: str,
    error_policy: str,
) -> NormalizationResult:
    if error_policy not in {"block", "skip"}:
        raise ValueError("error_policy must be block or skip")
    records = _read_path(document, mapping.record_path)
    if not isinstance(records, list):
        return _failed("映射的记录路径不是数组")
    if len(records) > MAX_RECORDS:
        return _failed("单批对话不能超过 10000 条")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return _failed(f"未知时区：{timezone_name}")

    items: list[ConversationInput] = []
    errors: list[NormalizationError] = []
    for index, raw_record in enumerate(records):
        try:
            items.append(_normalize_record(raw_record, mapping, timezone))
        except (TypeError, ValueError, KeyError) as error:
            errors.append(NormalizationError(row_index=index, message=str(error)))
    if errors and error_policy == "block":
        items = []
    return NormalizationResult(items=tuple(items), errors=tuple(errors))


def _walk_arrays(
    value: Any,
    path: str,
    depth: int,
    max_depth: int,
    output: list[ArrayCandidate],
) -> None:
    if depth > max_depth:
        return
    if isinstance(value, list):
        object_items = [item for item in value if isinstance(item, dict)]
        if value:
            output.append(
                ArrayCandidate(
                    path=path,
                    length=len(value),
                    object_ratio=len(object_items) / len(value),
                    sample=tuple(object_items[:3]),
                )
            )
        for index, item in enumerate(value[:3]):
            _walk_arrays(item, f"{path}.{index}", depth + 1, max_depth, output)
    elif isinstance(value, dict):
        for key, item in value.items():
            child_path = key if path == "$" else f"{path}.{key}"
            _walk_arrays(item, child_path, depth + 1, max_depth, output)


def _normalize_record(
    raw_record: Any, mapping: ImportMapping, timezone: ZoneInfo
) -> ConversationInput:
    if not isinstance(raw_record, dict):
        raise TypeError("记录必须是对象")
    occurred_at = _parse_datetime(_required(raw_record, mapping.occurred_at_path), timezone)
    messages = _messages(raw_record, mapping)
    if not messages or not any(message["content"].strip() for message in messages):
        raise ValueError("对话消息不能为空")
    external_value = _optional(raw_record, mapping.id_path)
    external_id = str(external_value).strip() if external_value is not None else ""
    if not external_id:
        canonical = json.dumps(
            raw_record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        external_id = f"json-{sha256(canonical.encode()).hexdigest()}"
    if len(external_id) > 255:
        raise ValueError("外部对话 ID 不能超过 255 个字符")
    scenario = _optional_text(raw_record, mapping.scenario_path, 128)
    status = _optional_text(raw_record, mapping.status_path, 32)
    return ConversationInput(
        external_id=external_id,
        scenario=scenario,
        status=status,
        occurred_at=occurred_at,
        body={"messages": messages, "raw": raw_record},
    )


def _messages(record: dict[str, Any], mapping: ImportMapping) -> list[dict[str, str]]:
    if mapping.message_mode == "qa_pair":
        question = _required_text(record, mapping.question_path)
        answer = _required_text(record, mapping.answer_path)
        return [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
    raw_messages = _required(record, mapping.messages_path)
    if not isinstance(raw_messages, list):
        raise TypeError("消息字段必须是数组")
    messages: list[dict[str, str]] = []
    for raw_message in raw_messages:
        if not isinstance(raw_message, dict):
            raise TypeError("消息记录必须是对象")
        role = _normalize_role(_required_text(raw_message, mapping.role_path))
        content = _required_text(raw_message, mapping.content_path)
        messages.append({"role": role, "content": content})
    return messages


def _parse_datetime(value: Any, timezone: ZoneInfo) -> datetime:
    if isinstance(value, bool):
        raise TypeError("时间字段无效")
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if abs(float(value)) >= 100_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, tz=UTC)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("时间字段不能为空")
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as error:
        raise ValueError("时间字段无法解析") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(UTC)


def _read_path(value: Any, path: str) -> Any:
    if path == "$":
        return value
    current = value
    for part in path.removeprefix("$.").split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise KeyError(f"找不到字段：{path}")
    return current


def _required(record: dict[str, Any], path: str | None) -> Any:
    if not path:
        raise ValueError("缺少必填字段映射")
    try:
        return _read_path(record, path)
    except KeyError as error:
        raise ValueError(f"找不到字段：{path}") from error


def _required_text(record: dict[str, Any], path: str | None) -> str:
    value = _required(record, path)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段 {path} 必须是非空文本")
    return value.strip()


def _optional(record: dict[str, Any], path: str | None) -> Any:
    if not path:
        return None
    try:
        return _read_path(record, path)
    except KeyError:
        return None


def _optional_text(record: dict[str, Any], path: str | None, max_length: int) -> str | None:
    value = _optional(record, path)
    if value is None:
        return None
    text = str(value).strip()
    if len(text) > max_length:
        raise ValueError(f"字段 {path} 不能超过 {max_length} 个字符")
    return text or None


def _normalize_role(role: str) -> str:
    normalized = role.casefold()
    if normalized in {"customer", "human", "user", "client"}:
        return "user"
    if normalized in {"bot", "assistant", "agent", "ai"}:
        return "assistant"
    return role


def _first_key(record: dict[str, Any], names: tuple[str, ...]) -> str | None:
    return next((name for name in names if name in record), None)


def _first_list_key(record: dict[str, Any], names: tuple[str, ...]) -> str | None:
    return next((name for name in names if isinstance(record.get(name), list)), None)


def _failed(message: str) -> NormalizationResult:
    return NormalizationResult(
        items=(), errors=(NormalizationError(row_index=-1, message=message),)
    )
