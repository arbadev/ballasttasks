"""Explicit demo entry point against a database owned by each test, never the local stack."""

import asyncio
import uuid
from collections import Counter
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
import sqlalchemy as sa

from app import seed_demo as entry
from app.application.use_cases.seed_demo import DemoSeedConflictError
from app.bootstrap import build_container, load_settings
from app.domain.project import DEFAULT_PROJECT_ID
from app.main import create_app
from tests.postgres import run_alembic, temporary_database

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)
# 21:00 in Chicago is already the next UTC day: the day every due date is anchored on.
CHICAGO = ZoneInfo("America/Chicago")
PAST_UTC_MIDNIGHT = datetime(2026, 9, 20, 2, tzinfo=UTC)
PASSWORD = "ballast-local-demo-only"


def demo_id(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"ballasttasks:demo:v2:{name}")


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[sa.Engine]:
    with temporary_database() as url:
        run_alembic(url, "upgrade", "head")
        monkeypatch.setenv("DATABASE__URL", url)
        monkeypatch.setenv("APP__ENV", "test")
        engine = sa.create_engine(url)
        try:
            yield engine
        finally:
            engine.dispose()


def seed(now: datetime = NOW) -> bool:
    return asyncio.run(entry.run(confirmed=True, clock=lambda: now))


def snapshot(engine: sa.Engine) -> dict[str, list[dict[str, Any]]]:
    with engine.connect() as connection:
        return {
            table: [
                dict(row)
                for row in connection.execute(
                    sa.text(f"SELECT * FROM {table} ORDER BY id")
                ).mappings()
            ]
            for table in ("users", "projects", "tasks", "task_activity", "task_steps")
        }


async def workspace() -> dict[str, Any]:
    container = build_container(load_settings(), clock=lambda: NOW)
    app = create_app(container=container)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        for email in ("demo@ballast.example", "lucia@ballast.example", "tomas@ballast.example"):
            login = await client.post("/auth/login", data={"username": email, "password": PASSWORD})
            assert login.status_code == 200
        login = await client.post(
            "/auth/login", data={"username": "demo@ballast.example", "password": PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assistant = await client.post(
            "/auth/login", data={"username": "assistant@ballast.example", "password": PASSWORD}
        )
        assert assistant.status_code == 401
        results = {}
        for path in ("/auth/me", "/users", "/projects", "/tasks?status=all", "/tasks/summary"):
            response = await client.get(path, headers=headers)
            assert response.status_code == 200
            results[path] = response.json()
        return results


def test_design_workspace_and_real_password_login(database: sa.Engine) -> None:
    before = snapshot(database)
    assert seed() is True
    data = asyncio.run(workspace())
    assert data["/auth/me"]["full_name"] == "Andres Barradas"
    assert [(p["full_name"], p["initials"], p["role_label"]) for p in data["/users"]["items"]] == [
        ("Andres Barradas", "AB", "owner"),
        ("Assistant", "AS", "system"),
        ("Lucía Marín", "LM", "backend"),
        ("Tomás Rey", "TR", "frontend"),
    ]
    assert [(p["key"], p["open_tasks"]) for p in data["/projects"]["items"]] == [
        ("BT", 11),
        ("IN", 2),
    ]
    tasks = {t["key"]: t for t in data["/tasks?status=all"]["items"]}
    assert data["/tasks?status=all"]["total"] == 16
    assert set(tasks) == {f"BT-{n:02}" for n in range(1, 15)} | {"IN-01", "IN-02"}
    assert Counter(t["status"] for t in tasks.values()) == {
        "todo": 8,
        "in_progress": 3,
        "testing": 2,
        "done": 3,
    }
    assert data["/tasks/summary"]["counts"] == {"all": 13, "mine": 7, "overdue": 1}
    assert data["/tasks/summary"]["signals"] == {
        "overdue": 1,
        # Same literal counts as web seed.design.test.ts: priority extends the window.
        "p0_at_risk": 2,
        "due_soon": 4,
        "needs_owner": 2,
    }
    expected = [
        (
            "BT-01",
            "Task CRUD endpoints with pagination and filters",
            "ab",
            "ab",
            3,
            "P0",
            95,
            4,
            0.8,
        ),
        ("BT-02", "Next.js task list and board", "ab", "ab", 7, "P0", 85, 3, 1),
        (
            "BT-03",
            "Generate-steps job: Celery worker + LanguageModel port",
            "tr",
            "tr",
            5,
            "P1",
            70,
            2,
            1,
        ),
        ("BT-04", "JWT authentication", "ab", None, 4, "P0", 90, 4, 4),
        ("BT-05", "Write PRD.md: overview, user stories, scope", "ab", "ab", -2, "P1", 75, 6, 3),
        ("BT-06", "Seed data and demo credentials", "lm", "lm", 8, "P1", 70, 3, 3),
        ("BT-07", "Rate limiting on the API", "ab", None, None, "P2", 55, 3, 3),
        (
            "BT-08",
            "GenAI write-up: prompt, validation, corrections",
            "ab",
            "ab",
            10,
            "P1",
            75,
            2,
            2,
        ),
        ("BT-09", "Presentation and code-review walkthrough", "ab", "ab", 13, "P1", 80, 2, 2),
        ("BT-10", "Unit tests at 80% coverage or more", "lm", "lm", 4, "P1", 65, 5, 0.5),
        ("BT-11", "Docker compose: five services from .env.example", "tr", "tr", 1, "P2", 50, 5, 1),
        ("BT-12", "Monorepo foundation and health endpoints", "ab", "ab", -6, "P0", 90, 12, 6),
        ("BT-13", "ADR 0002: ports and adapters", "ab", "ab", -8, "P2", 60, 11, 8),
        ("BT-14", "Pre-commit: ruff, mypy, import-linter", "tr", "tr", -7, "P3", 40, 10, 7),
        (
            "IN-01",
            "Review Vectal task detail for assistant patterns",
            "ab",
            "ab",
            None,
            "P3",
            30,
            1,
            1,
        ),
        ("IN-02", "Confirm the panel slot with the recruiter", "ab", "ab", 0, "P1", 70, 1, 1),
    ]
    for key, title, creator, owner, due, priority, importance, created, updated in expected:
        task = tasks[key]
        assert task["title"] == title
        assert task["created_by"] == str(demo_id(creator))
        assert task["assignee_id"] == (str(demo_id(owner)) if owner else None)
        assert task["due_date"] == (
            (NOW.date() + timedelta(days=due)).isoformat() if due is not None else None
        )
        assert (task["priority"], task["importance"]) == (priority, importance)
        assert datetime.fromisoformat(task["created_at"]) == NOW - timedelta(days=created)
        assert datetime.fromisoformat(task["updated_at"]) == NOW - timedelta(days=updated)
        assert task["completed_at"] == (task["updated_at"] if task["status"] == "done" else None)
        assert task["project_id"] == str(
            DEFAULT_PROJECT_ID if key.startswith("IN") else demo_id("ballast")
        )
    assert tasks["BT-01"]["description"] == (
        "FastAPI routes under /tasks. Filter by status and due date, paginate with limit/offset. "
        "The Pydantic models own the contract — run npm run gen:api after every change."
    )
    after = snapshot(database)
    assert len(after["task_activity"]) == 16
    for task in after["tasks"]:
        [creation] = [event for event in after["task_activity"] if event["task_id"] == task["id"]]
        assert creation["kind"] == "log"
        assert creation["text"] == "Created the task"
        assert creation["actor_id"] == task["created_by"]
        assert creation["created_at"] == task["created_at"]
    inbox = next(p for p in after["projects"] if p["id"] == DEFAULT_PROJECT_ID)
    assert {k: v for k, v in inbox.items() if k != "next_task_number"} == {
        k: v for k, v in before["projects"][0].items() if k != "next_task_number"
    }
    assert all(u["hashed_password"] != PASSWORD for u in after["users"])


def test_existing_inbox_data_survives_and_keys_continue(database: sa.Engine) -> None:
    async def arrange() -> None:
        container = build_container(load_settings(), clock=lambda: NOW)
        try:
            async with container.request_scope() as scope:
                user = await scope.register_user.execute(
                    email="other@example.com", password="private-test-password", full_name="Other"
                )
                await scope.create_task.execute(title="Keep me", created_by=user.id)
        finally:
            await container.aclose()

    asyncio.run(arrange())
    before = snapshot(database)
    assert seed()
    after = snapshot(database)
    assert all(user in after["users"] for user in before["users"])
    assert all(task in after["tasks"] for task in before["tasks"])
    assert {task["key"] for task in after["tasks"] if task["project_id"] == DEFAULT_PROJECT_ID} == {
        "IN-01",
        "IN-02",
        "IN-03",
    }
    assert not seed()
    assert snapshot(database) == after


def test_concurrent_invocations_do_not_duplicate_or_allocate_extra_keys(
    database: sa.Engine,
) -> None:
    async def together() -> list[bool]:
        results = await asyncio.gather(
            entry.run(confirmed=True, clock=lambda: NOW),
            entry.run(confirmed=True, clock=lambda: NOW),
        )
        return list(results)

    assert sorted(asyncio.run(together())) == [False, True]
    data = snapshot(database)
    assert len(data["users"]) == 4
    assert len(data["tasks"]) == 16
    assert sorted(p["next_task_number"] for p in data["projects"]) == [3, 15]


def test_rerun_is_byte_for_byte_unchanged_even_days_later(database: sa.Engine) -> None:
    assert seed()
    before = snapshot(database)
    assert seed(NOW + timedelta(days=20)) is False
    assert snapshot(database) == before


def due_dates(engine: sa.Engine) -> dict[str, date | None]:
    return {task["key"]: task["due_date"] for task in snapshot(engine)["tasks"]}


def test_rerun_is_unchanged_when_the_connection_time_zone_is_not_utc(
    database: sa.Engine,
) -> None:
    name = database.url.database
    with database.begin() as connection:
        connection.execute(sa.text(f"ALTER DATABASE \"{name}\" SET TimeZone = 'America/Chicago'"))
    database.dispose()
    with database.connect() as connection:
        assert connection.execute(sa.text("SHOW TimeZone")).scalar() == "America/Chicago"
        stored = connection.execute(sa.text("SELECT now()")).scalar()
    assert stored is not None
    assert stored.utcoffset() != timedelta(0)

    assert seed(PAST_UTC_MIDNIGHT) is True
    before = snapshot(database)
    assert due_dates(database)["BT-01"] == date(2026, 9, 23)
    assert seed(PAST_UTC_MIDNIGHT) is False
    assert snapshot(database) == before


def test_due_dates_follow_the_clocks_utc_day_not_its_local_day(database: sa.Engine) -> None:
    assert seed(PAST_UTC_MIDNIGHT.astimezone(CHICAGO)) is True
    assert due_dates(database)["BT-01"] == date(2026, 9, 23)
    assert seed(PAST_UTC_MIDNIGHT.astimezone(CHICAGO)) is False


@pytest.mark.parametrize("collision", ["email", "user_id", "project_key", "project_id", "task_id"])
def test_conflicting_existing_records_are_not_repurposed(
    database: sa.Engine, collision: str
) -> None:
    async def arrange() -> None:
        container = build_container(load_settings())
        try:
            async with container.request_scope() as scope:
                user = await scope.register_user.execute(
                    email="unrelated@example.com",
                    password="private-test-password",
                    full_name="Unrelated",
                )
                if collision in {"email", "user_id"}:
                    user = replace(
                        user,
                        id=demo_id("ab") if collision == "user_id" else uuid.uuid4(),
                        email="demo@ballast.example"
                        if collision == "email"
                        else "another@example.com",
                    )
                    await scope.users.add(user)
                if collision in {"project_key", "project_id"}:
                    project = (
                        await scope.create_project.execute(
                            name="Unrelated", key="BT" if collision == "project_key" else "OTHER"
                        )
                    ).project
                    if collision == "project_id":
                        project.id = demo_id("ballast")
                        await scope.projects.add(replace(project, key="ELSE"))
                task = await scope.create_task.execute(title="Do not erase", created_by=user.id)
                if collision == "task_id":
                    task.id = demo_id("t16")
                    task.key = str(await scope.projects.allocate_task_key(DEFAULT_PROJECT_ID))
                    await scope.tasks.add(task)
        finally:
            await container.aclose()

    asyncio.run(arrange())
    before = snapshot(database)
    with pytest.raises(DemoSeedConflictError, match="conflict"):
        seed()
    assert snapshot(database) == before


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE users SET full_name = 'Edited' WHERE role_label = 'owner'",
        "UPDATE users SET hashed_password = 'changed-private-hash' WHERE role_label = 'owner'",
        "UPDATE projects SET name = 'Edited' WHERE key = 'BT'",
        "UPDATE tasks SET title = 'Edited' WHERE key = 'BT-01'",
        "DELETE FROM tasks WHERE key = 'BT-01'",
        "DELETE FROM task_activity WHERE task_id = (SELECT id FROM tasks WHERE key = 'BT-01')",
    ],
)
def test_edits_password_changes_and_partial_seeds_are_preserved(
    database: sa.Engine, change: str
) -> None:
    seed()
    with database.begin() as connection:
        connection.execute(sa.text(change))
    before = snapshot(database)
    with pytest.raises(DemoSeedConflictError, match="conflict"):
        seed()
    assert snapshot(database) == before


def test_failure_on_last_task_rolls_back_every_row_and_key(
    database: sa.Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    with database.begin() as connection:
        connection.execute(
            sa.text("""
            CREATE FUNCTION reject_last_demo_task() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.title = 'Confirm the panel slot with the recruiter' THEN
                    RAISE EXCEPTION 'test-only insertion failure';
                END IF;
                RETURN NEW;
            END $$
        """)
        )
        connection.execute(
            sa.text(
                "CREATE TRIGGER reject_demo BEFORE INSERT ON tasks "
                "FOR EACH ROW EXECUTE FUNCTION reject_last_demo_task()"
            )
        )
    before = snapshot(database)
    with pytest.raises(sa.exc.ProgrammingError, match="test-only insertion failure"):
        seed()
    assert snapshot(database) == before
    assert entry.main([entry.CONFIRM_FLAG]) == 1
    output = capsys.readouterr()
    assert "test-only insertion failure" not in output.out + output.err
    assert "Demo seed failed" in output.err
    assert snapshot(database) == before
    with database.begin() as connection:
        connection.execute(sa.text("DROP TRIGGER reject_demo ON tasks"))
    assert seed()
    assert len(snapshot(database)["tasks"]) == 16


def test_production_entry_point_refuses_even_when_confirmed(
    database: sa.Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("APP__ENV", "production")
    before = snapshot(database)
    assert entry.main([entry.CONFIRM_FLAG]) == 1
    assert "production" in capsys.readouterr().err
    assert snapshot(database) == before


def test_unconfirmed_entry_point_writes_nothing(
    database: sa.Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    before = snapshot(database)
    assert entry.main([]) == 1
    assert entry.CONFIRM_FLAG in capsys.readouterr().err
    assert snapshot(database) == before
    with pytest.raises(entry.DemoSeedRefusedError, match=entry.CONFIRM_FLAG):
        asyncio.run(entry.run(confirmed=False, clock=lambda: NOW))
    assert snapshot(database) == before


def test_cli_is_explicit_and_reports_success_without_credentials(
    database: sa.Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    # Merely constructing the normal app must not seed anything.
    async def startup() -> None:
        app = create_app()
        async with app.router.lifespan_context(app):
            pass

    asyncio.run(startup())
    assert snapshot(database)["users"] == []
    assert entry.main([entry.CONFIRM_FLAG]) == 0
    assert entry.main([entry.CONFIRM_FLAG]) == 0
    output = capsys.readouterr()
    assert "created" in output.out
    assert "unchanged" in output.out
    assert PASSWORD not in output.out + output.err
    assert len(snapshot(database)["tasks"]) == 16
