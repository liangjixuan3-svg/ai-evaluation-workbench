from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.main  # noqa: F401 - register all SQLAlchemy models
from app.config import settings
from app.db import session_factory
from app.demo.qa_data import clear_qa_demo_data, seed_qa_demo_data


def main() -> None:
    parser = argparse.ArgumentParser(description="加入或清理 QA 审核工作台演示数据")
    parser.add_argument("--清理", "--clear", action="store_true", dest="clear")
    args = parser.parse_args()
    url = make_url(settings.database_url)
    print(f"目标数据库：{url.host or 'localhost'}/{url.database or ''}")

    with session_factory() as session:
        if args.clear:
            result = clear_qa_demo_data(session)
            print(f"已清理 {result['task_count']} 条 QA 演示任务。")
        else:
            result = seed_qa_demo_data(session)
            print(f"QA 演示任务已就绪：{result['task_count']} 条（四种状态各一条）。")


if __name__ == "__main__":
    main()
