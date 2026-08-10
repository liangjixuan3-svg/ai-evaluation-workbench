from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.main  # noqa: F401
from app.db import Base
from app.demo.retest_data import seed_retest_demo_data
from app.retest.service import mark_published, retest_workspace, retest_workspace_detail


def test_retest_demo_is_idempotent_and_ready_after_publish() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)

    with Session(engine, expire_on_commit=False) as session:
        first = seed_retest_demo_data(session, model="judge-v1")
        second = seed_retest_demo_data(session, model="judge-v1")
        workspace = retest_workspace(session)

        assert first == second == {"pending_publish_count": 1}
        assert workspace["summary"]["pending_publish_count"] == 1
        version_id = workspace["pending_publish"][0]["qa_version_id"]
        run = mark_published(session, version_id, "演示运营员", "演示知识库已上线")
        from app.retest.service import build_retest_sample

        build_retest_sample(session, run.id)
        assert retest_workspace_detail(session, run.id)["workspace_state"] == "ready"

    engine.dispose()
