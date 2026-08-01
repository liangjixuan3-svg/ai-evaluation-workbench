from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evaluation.models import PromptVersion
from app.evaluation.openai_compatible import DEFAULT_EVALUATION_INSTRUCTIONS
from app.shared.types import utc_now

PROMPT_NAME = "customer-support-judge"
MAX_PROMPT_LENGTH = 20_000


class PromptVersionError(ValueError):
    pass


class PromptVersionConflict(PromptVersionError):
    pass


def ensure_default_prompt(session: Session) -> PromptVersion:
    existing = session.scalar(
        select(PromptVersion)
        .where(PromptVersion.name == PROMPT_NAME)
        .order_by(PromptVersion.created_at)
    )
    if existing is not None:
        return existing
    now = utc_now()
    prompt = PromptVersion(
        name=PROMPT_NAME,
        version="v1",
        content=DEFAULT_EVALUATION_INSTRUCTIONS,
        active=True,
        published_at=now,
    )
    session.add(prompt)
    session.commit()
    return prompt


def list_prompt_versions(session: Session) -> list[PromptVersion]:
    ensure_default_prompt(session)
    return list(
        session.scalars(
            select(PromptVersion)
            .where(PromptVersion.name == PROMPT_NAME)
            .order_by(PromptVersion.created_at.desc(), PromptVersion.id.desc())
        )
    )


def create_prompt_draft(session: Session, source_id: str) -> PromptVersion:
    source = _prompt(session, source_id)
    if source.published_at is None:
        raise PromptVersionError("只能从已发布版本创建草稿")
    existing_draft = session.scalar(
        select(PromptVersion).where(
            PromptVersion.name == source.name, PromptVersion.published_at.is_(None)
        )
    )
    if existing_draft is not None:
        raise PromptVersionConflict("已经存在一个待编辑草稿")
    versions = list(
        session.scalars(select(PromptVersion.version).where(PromptVersion.name == source.name))
    )
    next_number = max((_version_number(value) for value in versions), default=0) + 1
    draft = PromptVersion(
        name=source.name,
        version=f"v{next_number}",
        content=source.content,
        active=False,
        published_at=None,
    )
    session.add(draft)
    session.commit()
    return draft


def update_prompt_draft(session: Session, prompt_id: str, content: str) -> PromptVersion:
    prompt = _prompt(session, prompt_id)
    if prompt.published_at is not None:
        raise PromptVersionConflict("已发布 Prompt 不可修改")
    prompt.content = _validated_content(content)
    session.commit()
    return prompt


def delete_prompt_draft(session: Session, prompt_id: str) -> None:
    prompt = _prompt(session, prompt_id)
    if prompt.published_at is not None:
        raise PromptVersionConflict("已发布 Prompt 不可删除")
    session.delete(prompt)
    session.commit()


def publish_prompt_draft(session: Session, prompt_id: str) -> PromptVersion:
    prompt = _prompt(session, prompt_id)
    if prompt.published_at is not None:
        raise PromptVersionConflict("该 Prompt 已经发布")
    prompt.content = _validated_content(prompt.content)
    duplicate = session.scalar(
        select(PromptVersion.id).where(
            PromptVersion.name == prompt.name,
            PromptVersion.published_at.is_not(None),
            PromptVersion.content == prompt.content,
        )
    )
    if duplicate is not None:
        raise PromptVersionError("Prompt 内容没有变化，无需发布新版本")
    for version in session.scalars(
        select(PromptVersion).where(
            PromptVersion.name == prompt.name, PromptVersion.active.is_(True)
        )
    ):
        version.active = False
    prompt.active = True
    prompt.published_at = utc_now()
    session.commit()
    return prompt


def prompt_payload(prompt: PromptVersion) -> dict[str, object]:
    return {
        "id": prompt.id,
        "name": prompt.name,
        "version": prompt.version,
        "content": prompt.content,
        "active": prompt.active,
        "published_at": prompt.published_at.isoformat() if prompt.published_at else None,
        "created_at": prompt.created_at.isoformat(),
    }


def _prompt(session: Session, prompt_id: str) -> PromptVersion:
    prompt = session.get(PromptVersion, prompt_id)
    if prompt is None or prompt.name != PROMPT_NAME:
        raise LookupError("评测 Prompt 版本不存在")
    return prompt


def _validated_content(content: str) -> str:
    value = content.strip()
    if not value:
        raise PromptVersionError("Prompt 内容不能为空")
    if len(value) > MAX_PROMPT_LENGTH:
        raise PromptVersionError(f"Prompt 内容不能超过 {MAX_PROMPT_LENGTH} 字")
    return value


def _version_number(version: str) -> int:
    return int(version[1:]) if version.startswith("v") and version[1:].isdigit() else 0
