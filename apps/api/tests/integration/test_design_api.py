"""The design's workspace as a client meets it, over real HTTP against real PostgreSQL.

Nothing is faked or overridden: register, log in, then projects, tasks with keys, the filtered
list, the summary, the people list and the profile. Also what only a real database can show:
how many statements a request issues, and which index the default listing uses.

The module has a database of its own, so its counts are exact whatever other modules commit.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
import sqlalchemy
from sqlalchemy import event, select
from sqlalchemy.dialects import postgresql

from app.application.task_query import TaskFilter, TaskSort
from app.bootstrap import Container, build_container, load_settings
from app.infrastructure.db.models.task import TaskModel
from app.infrastructure.db.repositories.task_queries import conditions, ordering
from app.infrastructure.db.unit_of_work import transactional_session
from app.main import create_app
from tests.postgres import run_alembic, temporary_database

pytestmark = pytest.mark.integration

# ``GET /tasks/{id_or_key}`` is the detail: the task as every other route shows it, plus what
# is attached to it.
NOTHING_ATTACHED: dict[str, object] = {"attachments": []}

PASSWORD = "correct horse battery"
INBOX = "00000000-0000-4000-8000-000000000001"


def today() -> date:
    return datetime.now(UTC).date()


def due_in(days: int) -> str:
    return (today() + timedelta(days=days)).isoformat()


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


async def test_the_workspace_end_to_end(client: httpx.AsyncClient) -> None:
    ada_id, ada = await sign_in(client, "Ada Lovelace")
    grace_id, grace = await sign_in(client, "grace hopper")

    # A profile, and the people list built from it: no email of anybody else.
    me = await client.patch("/auth/me", json={"role_label": "backend"}, headers=ada)
    assert me.status_code == 200, me.text
    assert (me.json()["initials"], me.json()["role_label"]) == ("AL", "backend")
    people = (await client.get("/users", headers=grace)).json()["items"]
    assert people == [
        {"id": ada_id, "full_name": "Ada Lovelace", "initials": "AL", "role_label": "backend"},
        {"id": grace_id, "full_name": "grace hopper", "initials": "GH", "role_label": None},
    ]

    # A project, and a key that cannot be taken twice.
    created = await client.post(
        "/projects", json={"name": "Ballast Tasks", "key": "BT", "color": "acc"}, headers=ada
    )
    assert created.status_code == 201, created.text
    ballast = created.json()
    taken = await client.post("/projects", json={"name": "Better", "key": "BT"}, headers=grace)
    assert taken.status_code == 409
    assert taken.json() == {"detail": "Project key 'BT' is already taken"}

    # Tasks take their key from their project; without one they land in the Inbox.
    async def create(**body: object) -> dict[str, object]:
        response = await client.post("/tasks", json=body, headers=ada)
        assert response.status_code == 201, response.text
        task: dict[str, object] = response.json()
        return task

    late = await create(title="late", project_id=ballast["id"], due_date=due_in(-3),
                        assignee_id=ada_id, priority="P1", importance=80)  # fmt: skip
    at_risk = await create(title="at risk", project_id=ballast["id"], due_date=due_in(1),
                           priority="P0", importance=95, description="FastAPI routes")  # fmt: skip
    inbox = await create(title="someday")
    shipped = await create(title="shipped", project_id=ballast["id"], status="done")
    assert [t["key"] for t in (late, at_risk, inbox, shipped)] == [
        "BT-01",
        "BT-02",
        "IN-01",
        "BT-03",
    ]
    assert late["attention"] == {
        "is_overdue": True,
        "is_due_soon": False,
        "is_p0_at_risk": False,
        "needs_owner": False,
        "days_until_due": -3,
        "urgency": 1030 + 8 + 6,
        "reasons": ["overdue"],
    }

    # By key, in any case; a key stays when the task moves to another project.
    assert (await client.get("/tasks/bt-2", headers=grace)).json() == at_risk | NOTHING_ATTACHED | {
        "steps": []
    }
    moved = await client.patch("/tasks/BT-02", json={"project_id": INBOX}, headers=grace)
    assert (moved.json()["project_id"], moved.json()["key"]) == (INBOX, "BT-02")
    assert (await client.get("/tasks/BT-99", headers=ada)).status_code == 404
    assert (await client.get("/tasks/nonsense", headers=ada)).status_code == 422
    unknown = await client.post(
        "/tasks", json={"title": "t", "project_id": str(uuid.uuid4())}, headers=ada
    )
    assert unknown.status_code == 422
    assert unknown.json()["detail"][0]["type"] == "unknown_project"

    # The list: filtered, sorted and counted by PostgreSQL.
    async def titles(query: str = "") -> list[str]:
        response = await client.get(f"/tasks{query}", headers=ada)
        assert response.status_code == 200, response.text
        return [task["title"] for task in response.json()["items"]]

    assert await titles() == ["late", "at risk", "someday"]
    assert await titles("?status=all") == ["late", "at risk", "someday", "shipped"]
    assert await titles("?scope=mine") == ["late"]
    assert await titles(f"?project_id={ballast['id']}&status=all") == ["late", "shipped"]
    assert await titles("?due=week&priority=P0") == ["at risk"]
    assert await titles("?assignee_id=unassigned&sort=importance") == ["at risk", "someday"]
    assert await titles("?q=fastapi") == ["at risk"]
    assert await titles("?signal=p0_at_risk") == ["at risk"]
    assert await titles("?sort=updated&limit=1") == ["at risk"]
    page = (await client.get("/tasks?limit=2&offset=2&status=all", headers=ada)).json()
    assert [t["title"] for t in page["items"]] == ["someday", "shipped"]
    assert (page["total"], page["limit"], page["offset"]) == (4, 2, 2)
    assert (await client.get("/tasks?limit=201", headers=ada)).status_code == 422

    # The numbers around it.
    summary = (await client.get("/tasks/summary", headers=ada)).json()
    assert summary["counts"] == {"all": 3, "mine": 1, "overdue": 1}
    assert [(p["key"], p["open_tasks"]) for p in summary["projects"]] == [("BT", 1), ("IN", 2)]
    assert summary["signals"] == {"overdue": 1, "p0_at_risk": 1, "due_soon": 1, "needs_owner": 2}
    projects = (await client.get("/projects", headers=ada)).json()["items"]
    assert [(p["name"], p["open_tasks"]) for p in projects] == [("Ballast Tasks", 1), ("Inbox", 2)]
    renamed = await client.patch(
        f"/projects/{ballast['id']}", json={"name": "Ballast"}, headers=ada
    )
    assert (renamed.json()["name"], renamed.json()["key"], renamed.json()["open_tasks"]) == (
        "Ballast",
        "BT",
        1,
    )


@pytest.mark.parametrize(
    ("path", "statements"),
    [
        # One to authenticate, then: the page, its total and batched steps/comments/attachments
        # tallies; the three counts of the summary; every project with its count.
        ("/tasks?status=all&limit=200", 4),
        ("/tasks/summary", 4),
        ("/projects", 2),
    ],
)
async def test_a_request_issues_the_same_few_statements_however_many_tasks_there_are(
    client: httpx.AsyncClient, container: Container, path: str, statements: int
) -> None:
    _, headers = await sign_in(client, "Ada Lovelace")
    project = (
        await client.post("/projects", json={"name": "Ballast", "key": "BT"}, headers=headers)
    ).json()
    issued: list[str] = []

    def record(_conn: object, _cursor: object, statement: str, *_: object) -> None:
        issued.append(statement)

    async def statements_of_one_request() -> int:
        issued.clear()
        event.listen(container.engine.sync_engine, "before_cursor_execute", record)
        try:
            response = await client.get(path, headers=headers)
        finally:
            event.remove(container.engine.sync_engine, "before_cursor_execute", record)
        assert response.status_code == 200, response.text
        return len(issued)

    async def add_tasks(count: int) -> None:
        for n in range(count):
            body = {"title": f"task {n}", "project_id": project["id"] if n % 2 else None}
            assert (await client.post("/tasks", json=body, headers=headers)).status_code == 201

    await add_tasks(2)
    with_two_tasks = await statements_of_one_request()
    await add_tasks(40)
    with_many_tasks = await statements_of_one_request()

    assert with_two_tasks == with_many_tasks == statements, issued


async def test_the_default_listing_reads_the_open_tasks_through_the_partial_index(
    client: httpx.AsyncClient, container: Container
) -> None:
    """A workspace ages into mostly done tasks; the default view must not read them."""
    user_id, _ = await sign_in(client, "Ada Lovelace")
    fill = sqlalchemy.text(
        "INSERT INTO tasks (id, title, status, created_by, created_at, updated_at, completed_at, "
        "project_id, key, priority, importance, due_date) "
        "SELECT gen_random_uuid(), 'task ' || n, "
        "CASE WHEN n % 100 = 0 THEN 'todo' ELSE 'done' END, :user, now(), now(), "
        "CASE WHEN n % 100 = 0 THEN NULL ELSE now() END, "
        ":inbox, 'EX-' || n, 2, 50, CURRENT_DATE + (n % 30) "
        "FROM generate_series(1, 5000) AS n"
    )
    default_listing = (
        select(TaskModel)
        .where(*conditions(TaskFilter(), today()))
        .order_by(*ordering(TaskSort.URGENCY, today()))
        .limit(50)
    )
    sql = str(
        default_listing.compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
            compile_kwargs={"literal_binds": True},
        )
    )

    async with transactional_session(container.session_factory) as session:
        await session.execute(fill, {"user": uuid.UUID(user_id), "inbox": uuid.UUID(INBOX)})
        await session.execute(sqlalchemy.text("ANALYZE tasks"))
        plan = "\n".join(row[0] for row in await session.execute(sqlalchemy.text(f"EXPLAIN {sql}")))

    print(plan)  # noqa: T201  (shown with `pytest -s`: the evidence the brief asks for)
    assert "ix_tasks_open_project_id_due_date" in plan, plan
    assert "Seq Scan" not in plan, plan
