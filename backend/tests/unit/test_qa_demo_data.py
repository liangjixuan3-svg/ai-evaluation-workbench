import os
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.main  # noqa: F401 - register all mapped tables
from app.alerts.models import Task
from app.db import Base
from app.ingestion.models import DataSource
from app.remediation.service import list_qa_workspace, qa_workspace_detail
from app.shared.enums import TaskType


def _load_demo_module() -> ModuleType:
    path = Path(__file__).parents[2] / "app" / "demo" / "qa_data.py"
    assert path.exists(), "QA 演示数据模块尚未实现"
    spec = spec_from_file_location("app.demo.qa_data", path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sqlite_engine(url: str = "sqlite://") -> Engine:
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool if url == "sqlite://" else None,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def test_demo_data_covers_four_states_and_is_idempotent() -> None:
    module = _load_demo_module()
    engine = _sqlite_engine()
    Base.metadata.create_all(engine)

    with Session(engine, expire_on_commit=False) as session:
        first = module.seed_qa_demo_data(session)
        second = module.seed_qa_demo_data(session)
        workspace = list_qa_workspace(session, "all")

        assert first == second
        assert first["task_count"] == 4
        assert workspace["summary"] == {
            "awaiting_generation_count": 1,
            "pending_review_count": 1,
            "approved_count": 1,
            "rejected_count": 1,
        }
        assert session.scalar(
            select(func.count()).select_from(Task).where(Task.type == TaskType.QA_REVIEW)
        ) == 4
        approved = next(item for item in workspace["items"] if item["state"] == "approved")
        detail = qa_workspace_detail(session, approved["task_id"])
        assert detail["draft"]["evidence"][0]["source_type"] == "business_reference"

    engine.dispose()


def test_demo_cleanup_only_removes_marked_data() -> None:
    module = _load_demo_module()
    engine = _sqlite_engine()
    Base.metadata.create_all(engine)

    with Session(engine, expire_on_commit=False) as session:
        real_source = DataSource(name="真实业务数据", kind="manual")
        session.add(real_source)
        session.commit()
        module.seed_qa_demo_data(session)

        removed = module.clear_qa_demo_data(session)

        assert removed["task_count"] == 4
        assert session.get(DataSource, real_source.id) is not None
        assert list_qa_workspace(session, "all")["items"] == []

    engine.dispose()


def test_demo_script_registers_all_models_when_run_independently(tmp_path: Path) -> None:
    database_path = tmp_path / "qa-demo.db"
    engine = _sqlite_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    script = Path(__file__).parents[2] / "scripts" / "加入QA演示数据.py"
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database_path}"}

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=script.parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "QA 演示任务已就绪：4 条" in result.stdout
