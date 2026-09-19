"""The revision that adds ``task_steps`` and ``task_activity``, against real PostgreSQL and a
database that already holds tasks.

What happens to existing rows: no task is touched; every existing task gets the entry the
design gives every task, "Created the task", by its creator and at its ``created_at``, so
its timeline starts where a new task's does. Existing tasks get no steps.
"""

import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy

from app.domain import activity_log
from tests.postgres import (
    INSERT_USER,
    TASK_PROJECT_COLUMNS,
    TASK_PROJECT_VALUES,
    run_alembic,
    temporary_database,
    user_row,
)

pytestmark = pytest.mark.integration

PREVIOUS_HEAD = "0ecd0978f6fd"
REVISION = "a1c5e7f90b24"

INSERT_TASK = sqlalchemy.text(
    "INSERT INTO tasks (id, title, status, created_by, created_at, updated_at, completed_at, "
    f"{TASK_PROJECT_COLUMNS}) "
    "VALUES (:id, :title, :status, :created_by, :created_at, :created_at, :completed_at, "
    f"{TASK_PROJECT_VALUES})"
)


@pytest.fixture
def database() -> Iterator[sqlalchemy.Engine]:
    with temporary_database() as database_url:
        engine = sqlalchemy.create_engine(database_url)
        yield engine
        engine.dispose()


def migrate(engine: sqlalchemy.Engine, action: str, revision: str) -> None:
    run_alembic(engine.url.render_as_string(hide_password=False), action, revision)


def rows(engine: sqlalchemy.Engine, sql: str) -> list[sqlalchemy.Row[tuple[object, ...]]]:
    with engine.connect() as connection:
        return list(connection.execute(sqlalchemy.text(sql)))


def tables(engine: sqlalchemy.Engine) -> set[str]:
    return set(sqlalchemy.inspect(engine).get_table_names())


def with_existing_tasks(engine: sqlalchemy.Engine) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Two tasks by two people, one of whom has since been deactivated."""
    migrate(engine, "upgrade", PREVIOUS_HEAD)
    ada, gone = user_row(), user_row(is_active=False)
    # SSO-only users have no password hash; they can own tasks and activity too.
    ada["hashed_password"] = None
    open_task, done_task = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(INSERT_USER, ada)
        connection.execute(INSERT_USER, gone)
        for task_id, title, status, creator, created_at, completed_at in (
            (open_task, "open", "todo", ada, "2026-01-05T09:00:00+00:00", None),
            (done_task, "done", "done", gone, "2026-01-06T10:30:00+00:00", "2026-01-07T09:00Z"),
        ):
            connection.execute(
                INSERT_TASK,
                {
                    "id": task_id,
                    "title": title,
                    "status": status,
                    "created_by": creator["id"],
                    "created_at": created_at,
                    "completed_at": completed_at,
                },
            )
    return open_task, done_task, gone["id"]


def test_the_revision_follows_user_identities(database: sqlalchemy.Engine) -> None:
    migrate(database, "upgrade", "head")

    assert {"task_steps", "task_activity"} <= tables(database)
    assert rows(database, "SELECT count(*) FROM task_steps") == [(0,)]
    assert rows(database, "SELECT count(*) FROM task_activity") == [(0,)]


def test_existing_tasks_are_untouched_and_each_gets_its_created_entry(
    database: sqlalchemy.Engine,
) -> None:
    open_task, done_task, gone = with_existing_tasks(database)
    before = rows(database, "SELECT * FROM tasks ORDER BY title")

    migrate(database, "upgrade", "head")

    assert rows(database, "SELECT * FROM tasks ORDER BY title") == before
    assert rows(database, "SELECT count(*) FROM task_steps") == [(0,)]
    entries = rows(
        database,
        "SELECT a.task_id, a.kind, a.text, a.actor_id = t.created_by, a.created_at = t.created_at "
        "FROM task_activity a JOIN tasks t ON t.id = a.task_id ORDER BY t.title",
    )
    assert entries == [
        (done_task, "log", activity_log.CREATED, True, True),
        (open_task, "log", activity_log.CREATED, True, True),
    ]
    assert rows(database, f"SELECT actor_id FROM task_activity WHERE task_id = '{done_task}'") == [
        (gone,)
    ]
    assert len(rows(database, "SELECT DISTINCT id FROM task_activity")) == 2


def test_upgrading_twice_from_the_previous_head_does_not_double_the_entries(
    database: sqlalchemy.Engine,
) -> None:
    with_existing_tasks(database)
    migrate(database, "upgrade", "head")
    migrate(database, "downgrade", PREVIOUS_HEAD)

    migrate(database, "upgrade", "head")

    assert rows(database, "SELECT count(*) FROM task_activity") == [(2,)]


def test_downgrade_drops_both_tables_and_leaves_the_tasks(database: sqlalchemy.Engine) -> None:
    open_task, _, _ = with_existing_tasks(database)
    before = rows(database, "SELECT * FROM tasks ORDER BY title")
    migrate(database, "upgrade", "head")
    with database.begin() as connection:
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO task_steps (id, task_id, title, done, position, created_at) "
                "VALUES (gen_random_uuid(), :task, 'a step', false, 0, now())"
            ),
            {"task": open_task},
        )

    migrate(database, "downgrade", PREVIOUS_HEAD)

    assert not {"task_steps", "task_activity"} & tables(database)
    assert rows(database, "SELECT * FROM tasks ORDER BY title") == before
    migrate(database, "downgrade", "base")
    assert tables(database) <= {"alembic_version"}


def test_the_tables_refuse_what_no_entity_could_be_rebuilt_from(
    database: sqlalchemy.Engine,
) -> None:
    open_task, _, gone = with_existing_tasks(database)
    migrate(database, "upgrade", "head")
    step = (
        "INSERT INTO task_steps (id, task_id, title, done, position, created_at) "
        "VALUES (gen_random_uuid(), '{task}', 'a step', false, {position}, now())"
    )
    entry = (
        "INSERT INTO task_activity (id, task_id, kind, text, actor_id, created_at) "
        "VALUES (gen_random_uuid(), '{task}', '{kind}', 'text', '{actor}', now())"
    )
    refused = [
        step.format(task=open_task, position=-1),
        step.format(task=uuid.uuid4(), position=0),
        entry.format(task=open_task, kind="rumour", actor=gone),
        entry.format(task=open_task, kind="log", actor=uuid.uuid4()),
        entry.format(task=uuid.uuid4(), kind="log", actor=gone),
    ]
    for statement in refused:
        with pytest.raises(sqlalchemy.exc.IntegrityError), database.begin() as connection:
            connection.execute(sqlalchemy.text(statement))

    # Two steps at one position are refused when the transaction ends, not before.
    connection = database.connect()
    transaction = connection.begin()
    connection.execute(sqlalchemy.text(step.format(task=open_task, position=0)))
    connection.execute(sqlalchemy.text(step.format(task=open_task, position=0)))
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        transaction.commit()
    connection.close()

    # Somebody the log names cannot be deleted; they can only be deactivated.
    with pytest.raises(sqlalchemy.exc.IntegrityError), database.begin() as connection:
        connection.execute(sqlalchemy.text(f"DELETE FROM users WHERE id = '{gone}'"))
