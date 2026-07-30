from __future__ import annotations

from app.imports.contracts import ImportMapping
from app.imports.parser import discover_record_arrays, normalize_records, suggest_mapping


def test_discovers_nested_records_and_normalizes_message_array() -> None:
    document = {
        "result": {
            "conversations": [
                {
                    "sessionId": "s-1",
                    "createdAt": "2026-07-30T09:00:00+08:00",
                    "scene": "退款进度",
                    "turns": [
                        {"speaker": "customer", "text": "退款进度？"},
                        {"speaker": "bot", "text": "请耐心等待。"},
                    ],
                    "extra": {"channel": "app"},
                }
            ]
        }
    }

    candidate = discover_record_arrays(document)[0]
    assert candidate.path == "result.conversations"
    suggestion = suggest_mapping(candidate.sample)
    assert suggestion.id_path == "sessionId"
    assert suggestion.occurred_at_path == "createdAt"
    assert suggestion.messages_path == "turns"

    mapping = ImportMapping(
        record_path="result.conversations",
        id_path="sessionId",
        occurred_at_path="createdAt",
        scenario_path="scene",
        message_mode="messages",
        messages_path="turns",
        role_path="speaker",
        content_path="text",
    )
    result = normalize_records(document, mapping, "Asia/Shanghai", "block")

    assert result.errors == ()
    assert result.items[0].scenario == "退款进度"
    assert result.items[0].body["messages"][0] == {
        "role": "user",
        "content": "退款进度？",
    }
    assert result.items[0].body["raw"]["extra"] == {"channel": "app"}


def test_normalizes_question_answer_and_uses_stable_hash_id() -> None:
    document = [{"time": 1722301200, "question": "Q", "answer": "A"}]
    mapping = ImportMapping(
        record_path="$",
        occurred_at_path="time",
        message_mode="qa_pair",
        question_path="question",
        answer_path="answer",
    )

    first = normalize_records(document, mapping, "Asia/Shanghai", "block")
    second = normalize_records(document, mapping, "Asia/Shanghai", "block")

    assert first.items[0].external_id == second.items[0].external_id
    assert first.items[0].body["messages"] == [
        {"role": "user", "content": "Q"},
        {"role": "assistant", "content": "A"},
    ]
    assert first.items[0].occurred_at.tzinfo is not None


def test_error_policy_blocks_or_skips_invalid_rows() -> None:
    document = [
        {"id": "ok", "time": "2026-07-30T09:00:00+08:00", "q": "Q", "a": "A"},
        {"id": "bad", "time": "not-a-time", "q": "Q", "a": "A"},
    ]
    mapping = ImportMapping(
        record_path="$",
        id_path="id",
        occurred_at_path="time",
        message_mode="qa_pair",
        question_path="q",
        answer_path="a",
    )

    blocked = normalize_records(document, mapping, "Asia/Shanghai", "block")
    skipped = normalize_records(document, mapping, "Asia/Shanghai", "skip")

    assert blocked.items == ()
    assert blocked.errors[0].row_index == 1
    assert len(skipped.items) == 1
    assert len(skipped.errors) == 1


def test_rejects_more_than_ten_thousand_records() -> None:
    mapping = ImportMapping(
        record_path="$",
        occurred_at_path="time",
        message_mode="qa_pair",
        question_path="q",
        answer_path="a",
    )
    document = [{"time": 1, "q": "Q", "a": "A"}] * 10_001

    result = normalize_records(document, mapping, "UTC", "block")

    assert result.items == ()
    assert result.errors[0].message == "单批对话不能超过 10000 条"
