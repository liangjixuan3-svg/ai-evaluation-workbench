from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    app = create_app()

    def override_session() -> Iterator[Session]:
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()


def test_prompt_draft_save_publish_and_lock(client: TestClient) -> None:
    listed = client.get("/api/evaluation-prompts")
    assert listed.status_code == 200
    default = listed.json()[0]
    assert default["version"] == "v1"
    assert default["active"] is True
    assert default["published_at"] is not None

    copied = client.post(
        "/api/evaluation-prompts/drafts", json={"source_id": default["id"]}
    )
    assert copied.status_code == 201
    draft = copied.json()
    assert draft["version"] == "v2"
    assert draft["active"] is False
    assert draft["published_at"] is None
    assert client.post(
        "/api/evaluation-prompts/drafts", json={"source_id": default["id"]}
    ).status_code == 409

    unchanged = client.post(f"/api/evaluation-prompts/{draft['id']}/publish")
    assert unchanged.status_code == 422

    saved = client.put(
        f"/api/evaluation-prompts/{draft['id']}",
        json={"content": f"{draft['content']}\n回答前先识别用户诉求。"},
    )
    assert saved.status_code == 200
    assert "识别用户诉求" in saved.json()["content"]

    published = client.post(f"/api/evaluation-prompts/{draft['id']}/publish")
    assert published.status_code == 200
    assert published.json()["active"] is True
    assert published.json()["published_at"] is not None

    versions = client.get("/api/evaluation-prompts").json()
    assert [item["version"] for item in versions] == ["v2", "v1"]
    assert [item["active"] for item in versions] == [True, False]
    assert client.put(
        f"/api/evaluation-prompts/{draft['id']}", json={"content": "不能修改"}
    ).status_code == 409


def test_prompt_draft_can_be_deleted_but_published_version_cannot(
    client: TestClient,
) -> None:
    default = client.get("/api/evaluation-prompts").json()[0]
    draft = client.post(
        "/api/evaluation-prompts/drafts", json={"source_id": default["id"]}
    ).json()

    deleted = client.delete(f"/api/evaluation-prompts/{draft['id']}")

    assert deleted.status_code == 204
    assert [item["id"] for item in client.get("/api/evaluation-prompts").json()] == [
        default["id"]
    ]
    assert client.delete(f"/api/evaluation-prompts/{default['id']}").status_code == 409
