"""Task CRUD through the real container: HTTP -> use case -> SQLAlchemy -> PostgreSQL."""

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest

from app.api.security import get_current_user_id
from app.bootstrap import build_container, load_settings
from app.main import create_app

pytestmark = pytest.mark.integration

USER_ID = uuid.uuid4()


@pytest.fixture
async def client(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    app = create_app(container=build_container(load_settings()))
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http,
    ):
        yield http


async def test_a_task_lives_through_create_read_update_and_delete(
    client: httpx.AsyncClient,
) -> None:
    assignee = str(uuid.uuid4())

    created = await client.post("/tasks", json={"title": "Write the report"})
    assert created.status_code == 201
    task = created.json()
    assert task["created_by"] == str(USER_ID)

    # Each request is its own transaction: what one committed, the next one reads.
    assert (await client.get(f"/tasks/{task['id']}")).json() == task
    assert task in (await client.get("/tasks")).json()["items"]

    patched = await client.patch(
        f"/tasks/{task['id']}", json={"status": "done", "assignee_id": assignee}
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "done"
    assert patched.json()["assignee_id"] == assignee
    assert patched.json()["completed_at"] is not None
    assert (await client.get(f"/tasks/{task['id']}")).json() == patched.json()

    assert (await client.delete(f"/tasks/{task['id']}")).status_code == 204
    assert (await client.get(f"/tasks/{task['id']}")).status_code == 404


async def test_a_rejected_request_stores_nothing(client: httpx.AsyncClient) -> None:
    before = (await client.get("/tasks")).json()

    assert (await client.post("/tasks", json={"title": "   "})).status_code == 422

    assert (await client.get("/tasks")).json() == before
