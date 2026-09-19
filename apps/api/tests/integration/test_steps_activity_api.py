"""Steps, comments and the activity log over real HTTP, real PostgreSQL and real Redis.

Nothing is faked or overridden: register, log in, then every new route. Also what only a
real database can show: how many statements the list costs once tasks have steps and
comments, that a log line commits or rolls back with the change it describes, and that
deleting a task removes its rows.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy
from sqlalchemy import event

from app.application.use_cases.update_task import TaskChanges, UpdateTask
from app.bootstrap import Container, build_container, load_settings
from app.domain.task import TaskStatus
from app.infrastructure.db.repositories.activity import SqlAlchemyActivityLog
from app.infrastructure.db.repositories.project import SqlAlchemyProjectRepository
from app.infrastructure.db.repositories.task import SqlAlchemyTaskRepository
from app.infrastructure.db.repositories.task_tallies import SqlAlchemyTaskTallies
from app.infrastructure.db.repositories.user_directory import SqlAlchemyUserDirectory
from app.infrastructure.db.unit_of_work import transactional_session
from app.main import create_app
from tests.postgres import run_alembic, temporary_database

pytestmark = pytest.mark.integration

PASSWORD = "correct horse battery"


@pytest.fixture
def database_url() -> Iterator[str]:
    with temporary_database() as url:
        run_alembic(url, "upgrade", "head")
        yield url


@pytest.fixture
def container(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Container:
    monkeypatch.setenv("DATABASE__URL", database_url)
    return build_container(load_settings())


@pytest.fixture
async def client(container: Container) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(container=container)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http,
    ):
        yield http


async def sign_in(client: httpx.AsyncClient, full_name: str) -> tuple[str, dict[str, str]]:
    email = f"{uuid.uuid4().hex}@example.com"
    registered = await client.post(
        "/auth/register", json={"email": email, "full_name": full_name, "password": PASSWORD}
    )
    assert registered.status_code == 201, registered.text
    login = await client.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return registered.json()["id"], {"Authorization": f"Bearer {login.json()['access_token']}"}


async def count(container: Container, table: str, task_id: str) -> int:
    async with transactional_session(container.session_factory) as session:
        found = await session.scalar(
            sqlalchemy.text(f"SELECT count(*) FROM {table} WHERE task_id = :task"),
            {"task": uuid.UUID(task_id)},
        )
    return int(found or 0)


async def test_the_detail_panel_end_to_end(client: httpx.AsyncClient, container: Container) -> None:
    andres_id, andres = await sign_in(client, "Andres Barradas")
    lucia_id, lucia = await sign_in(client, "Lucía Marín")
    project = await client.post("/projects", json={"name": "Ballast", "key": "BT"}, headers=andres)
    created = await client.post(
        "/tasks", json={"title": "Task CRUD", "project_id": project.json()["id"]}, headers=andres
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert (task["key"], task["steps_total"], task["steps_done"], task["comments_count"]) == (
        "BT-01",
        0,
        0,
        0,
    )
    base = f"/tasks/{task['key']}"

    # Steps: one typed into the panel, three accepted together, then ticked, reordered, removed.
    typed = await client.post(f"{base}/steps", json={"title": "  Task entity  "}, headers=andres)
    assert typed.status_code == 201, typed.text
    accepted = await client.post(
        f"{base}/steps/bulk", json={"titles": ["Port", "Use cases", "Routes"]}, headers=lucia
    )
    assert accepted.status_code == 201, accepted.text
    entity, (port, use_cases, routes) = typed.json(), accepted.json()["items"]
    assert [s["position"] for s in (entity, port, use_cases, routes)] == [0, 1, 2, 3]
    ticked = await client.patch(f"{base}/steps/{entity['id']}", json={"done": True}, headers=lucia)
    assert (ticked.status_code, ticked.json()["done"]) == (200, True)
    order = [routes["id"], entity["id"], port["id"], use_cases["id"]]
    reordered = await client.put(f"{base}/steps/order", json={"step_ids": order}, headers=andres)
    assert reordered.status_code == 200, reordered.text
    removed = await client.delete(f"{base}/steps/{port['id']}", headers=andres)
    assert removed.status_code == 204

    # The task, the way the panel reads it.
    one = (await client.get(base, headers=lucia)).json()
    assert [(s["title"], s["position"], s["done"]) for s in one["steps"]] == [
        ("Routes", 0, False),
        ("Task entity", 1, True),
        ("Use cases", 2, False),
    ]
    assert (one["steps_total"], one["steps_done"]) == (3, 1)

    # Changes, and a comment by somebody else.
    await client.patch(
        base, json={"status": "in_progress", "assignee_id": lucia_id}, headers=andres
    )
    said = await client.post(f"{base}/comments", json={"text": " due_before too? "}, headers=lucia)
    assert said.status_code == 201, said.text
    assert said.json()["actor"] == {"id": lucia_id, "full_name": "Lucía Marín", "initials": "LM"}

    feed = (await client.get(f"{base}/activity", headers=andres)).json()
    assert [(e["kind"], e["text"], e["actor"]["full_name"]) for e in feed["items"]] == [
        ("comment", "due_before too?", "Lucía Marín"),
        ("log", "Assigned to Lucía Marín", "Andres Barradas"),
        ("log", "Moved To Do → In Progress", "Andres Barradas"),
        ("log", "Completed step “Task entity”", "Lucía Marín"),
        ("log", "Drafted 3 steps · added by Lucía", "Lucía Marín"),
        ("log", "Added step “Task entity”", "Andres Barradas"),
        ("log", "Created the task", "Andres Barradas"),
    ]
    assert (feed["total"], feed["limit"], feed["offset"]) == (7, 50, 0)
    assert "@" not in str(feed)
    page = (await client.get(f"{base}/activity?limit=2&offset=5", headers=andres)).json()
    assert [e["text"] for e in page["items"]] == ["Added step “Task entity”", "Created the task"]

    listed = (await client.get("/tasks", headers=andres)).json()["items"]
    assert [(t["steps_total"], t["steps_done"], t["comments_count"]) for t in listed] == [(3, 1, 1)]
    assert datetime.fromisoformat(listed[0]["updated_at"]) >= datetime.fromisoformat(
        said.json()["created_at"]
    )

    # Failure paths, over the real stack.
    no_token = await client.post(f"{base}/comments", json={"text": "anonymous"})
    assert no_token.status_code == 401
    assert (await client.get("/tasks/BT-99/activity", headers=andres)).status_code == 404
    assert (await client.get("/tasks/nonsense/steps", headers=andres)).status_code == 422
    nul = await client.post(f"{base}/comments", json={"text": "nul\x00byte"}, headers=andres)
    assert (nul.status_code, nul.json()["detail"][0]["type"]) == (422, "invalid_comment")
    nul_step = await client.post(f"{base}/steps", json={"title": "nul\x00byte"}, headers=andres)
    assert (nul_step.status_code, nul_step.json()["detail"][0]["type"]) == (422, "invalid_step")
    stale = await client.put(f"{base}/steps/order", json={"step_ids": order}, headers=andres)
    assert (stale.status_code, stale.json()["detail"][0]["type"]) == (422, "invalid_step_order")
    gone = await client.patch(f"{base}/steps/{port['id']}", json={"done": True}, headers=andres)
    assert gone.status_code == 404
    assert (await client.get(f"{base}/activity", headers=andres)).json()["total"] == 7

    # Deleting the task deletes its steps and its activity.
    assert (await count(container, "task_steps", task["id"])) == 3
    assert (await count(container, "task_activity", task["id"])) == 7
    assert (await client.delete(base, headers=andres)).status_code == 204
    assert (await count(container, "task_steps", task["id"])) == 0
    assert (await count(container, "task_activity", task["id"])) == 0
    assert andres_id != lucia_id


async def test_the_list_costs_the_same_few_statements_however_many_steps_and_comments(
    client: httpx.AsyncClient, container: Container
) -> None:
    """No query per task: the caller, the page, its total, and ONE statement that tallies
    the steps and the comments of the whole page."""
    _, headers = await sign_in(client, "Ada Lovelace")
    issued: list[str] = []

    def record(_conn: object, _cursor: object, statement: str, *_: object) -> None:
        issued.append(statement)

    async def statements_of(path: str) -> list[str]:
        issued.clear()
        event.listen(container.engine.sync_engine, "before_cursor_execute", record)
        try:
            response = await client.get(path, headers=headers)
        finally:
            event.remove(container.engine.sync_engine, "before_cursor_execute", record)
        assert response.status_code == 200, response.text
        return list(issued)

    async def add_tasks(how_many: int, *, steps: int, comments: int) -> None:
        for n in range(how_many):
            task = (
                await client.post("/tasks", json={"title": f"task {n}"}, headers=headers)
            ).json()
            if steps:
                titles = [f"step {s}" for s in range(steps)]
                await client.post(
                    f"/tasks/{task['id']}/steps/bulk", json={"titles": titles}, headers=headers
                )
            for c in range(comments):
                await client.post(
                    f"/tasks/{task['id']}/comments", json={"text": f"comment {c}"}, headers=headers
                )

    await add_tasks(2, steps=0, comments=0)
    with_little = await statements_of("/tasks?limit=200")
    await add_tasks(12, steps=5, comments=3)
    with_a_lot = await statements_of("/tasks?limit=200")

    assert len(with_little) == len(with_a_lot) == 4, with_a_lot
    assert sum("task_steps" in statement for statement in with_a_lot) == 1
    assert sum("task_activity" in statement for statement in with_a_lot) == 1
    listed = (await client.get("/tasks?limit=200", headers=headers)).json()["items"]
    assert (
        sorted((t["steps_total"], t["comments_count"]) for t in listed)
        == [(0, 0)] * 2 + [(5, 3)] * 12
    )

    # An empty page asks for no tallies at all.
    assert len(await statements_of("/tasks?q=nothing-matches-this")) == 3


async def test_the_tallies_of_many_tasks_are_one_statement(container: Container) -> None:
    issued: list[str] = []

    def record(_conn: object, _cursor: object, statement: str, *_: object) -> None:
        issued.append(statement)

    async with transactional_session(container.session_factory) as session:
        event.listen(container.engine.sync_engine, "before_cursor_execute", record)
        try:
            tallies = await SqlAlchemyTaskTallies(session).for_tasks(
                [uuid.uuid4() for _ in range(150)]
            )
            nothing = await SqlAlchemyTaskTallies(session).for_tasks([])
        finally:
            event.remove(container.engine.sync_engine, "before_cursor_execute", record)

    assert (len(tallies), dict(nothing), len(issued)) == (150, {}, 1)


async def test_a_log_line_commits_or_rolls_back_with_the_change_it_describes(
    client: httpx.AsyncClient, container: Container
) -> None:
    user_id, headers = await sign_in(client, "Ada Lovelace")
    task = (await client.post("/tasks", json={"title": "Write the report"}, headers=headers)).json()

    async def complete_then_fail() -> None:
        async with transactional_session(container.session_factory) as session:
            await UpdateTask(
                SqlAlchemyTaskRepository(session),
                SqlAlchemyUserDirectory(session),
                SqlAlchemyProjectRepository(session),
                SqlAlchemyActivityLog(session),
            ).execute(
                uuid.UUID(task["id"]),
                TaskChanges(status=TaskStatus.DONE),
                actor_id=uuid.UUID(user_id),
            )
            raise RuntimeError("something failed later in the request")

    with pytest.raises(RuntimeError, match="later in the request"):
        await complete_then_fail()

    after = (await client.get(f"/tasks/{task['id']}", headers=headers)).json()
    feed = (await client.get(f"/tasks/{task['id']}/activity", headers=headers)).json()
    assert after["status"] == "todo"
    assert [entry["text"] for entry in feed["items"]] == ["Created the task"]


async def test_entries_written_at_one_instant_keep_the_order_they_were_written_in(
    client: httpx.AsyncClient,
) -> None:
    _, headers = await sign_in(client, "Ada Lovelace")
    task = (await client.post("/tasks", json={"title": "Write the report"}, headers=headers)).json()
    tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()

    for _ in range(5):
        await client.patch(
            f"/tasks/{task['id']}",
            json={"status": "testing", "priority": "P0", "due_date": tomorrow},
            headers=headers,
        )
        await client.patch(
            f"/tasks/{task['id']}",
            json={"status": "todo", "priority": "P2", "due_date": None},
            headers=headers,
        )

    feed = (await client.get(f"/tasks/{task['id']}/activity", headers=headers)).json()
    one_round = [
        "Priority P0 → P2",
        "Due date cleared",
        "Moved Testing → To Do",
        "Priority P2 → P0",
        "Due date moved to tomorrow",
        "Moved To Do → Testing",
    ]
    assert [entry["text"] for entry in feed["items"]] == one_round * 5 + ["Created the task"]
