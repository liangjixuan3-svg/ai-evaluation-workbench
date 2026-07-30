import asyncio
from collections.abc import Iterator

import httpx

from app.db import get_session
from app.main import create_app


class EmptySession:
    def scalars(self, statement: object) -> Iterator[object]:
        return iter(())

    def scalar(self, statement: object) -> int:
        return 0


def test_workbench_returns_stable_task_first_contract() -> None:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: EmptySession()

    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/workbench")

    response = asyncio.run(request())

    assert response.status_code == 200
    payload = response.json()
    assert payload["priority_items"] == []
    assert set(payload["counts"]) == {
        "new_alerts",
        "pending_attributions",
        "pending_qa",
        "pending_retests",
    }
