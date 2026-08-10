from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.main  # noqa: F401
from app.config import settings
from app.db import session_factory
from app.demo.retest_data import seed_retest_demo_data


def main() -> None:
    url = make_url(settings.database_url)
    print(f"目标数据库：{url.host or 'localhost'}/{url.database or ''}")
    model = settings.llm_model or "deepseek-chat"
    with session_factory() as session:
        result = seed_retest_demo_data(session, model=model)
    print(f"发布复测演示数据已就绪：{result['pending_publish_count']} 条待发布 QA。")


if __name__ == "__main__":
    main()
