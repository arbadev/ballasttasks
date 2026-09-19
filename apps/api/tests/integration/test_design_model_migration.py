"""The revision that brings the design's model (projects, keys, a fourth status, priority,
importance, role labels), against real PostgreSQL and a database that already holds tasks."""

import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy

from tests.postgres import INSERT_USER, run_alembic, temporary_database, user_row

pytestmark = pytest.mark.integration

PREVIOUS_HEAD = "fa7b13ec7508"
INBOX = uuid.UUID("00000000-0000-4000-8000-000000000001")

INSERT_OLD_TASK = sqlalchemy.text(
    "INSERT INTO tasks (id, title, status, created_by, created_at, updated_at, completed_at) "
    "VALUES (:id, :title, :status, :created_by, :created_at, :created_at, :completed_at)"
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


def with_existing_tasks(engine: sqlalchemy.Engine) -> dict[str, uuid.UUID]:
    """Three tasks written before projects existed; ``third`` and ``second`` share a
    ``created_at``, so their numbering falls back to the id."""
    migrate(engine, "upgrade", PREVIOUS_HEAD)
    creator = user_row()
    low, high = sorted((uuid.uuid4(), uuid.uuid4()))
    ids = {"first": uuid.uuid4(), "second": low, "third": high}
    tasks = [
        ("first", "in_progress", "2026-01-05T09:00:00+00:00", None),
        ("second", "done", "2026-01-06T09:00:00+00:00", "2026-01-07T09:00:00+00:00"),
        ("third", "todo", "2026-01-06T09:00:00+00:00", None),
    ]
    with engine.begin() as connection:
        connection.execute(INSERT_USER, creator)
        for title, status, created_at, completed_at in tasks:
            connection.execute(
                INSERT_OLD_TASK,
                {
                    "id": ids[title],
                    "title": title,
                    "status": status,
                    "created_by": creator["id"],
                    "created_at": created_at,
                    "completed_at": completed_at,
                },
            )
    return ids


def test_an_empty_database_gets_the_inbox_ready_to_hand_out_its_first_key(
    database: sqlalchemy.Engine,
) -> None:
    migrate(database, "upgrade", "head")

    assert rows(database, "SELECT id, name, key, color, next_task_number FROM projects") == [
        (INBOX, "Inbox", "IN", None, 1)
    ]


def test_existing_tasks_keep_their_values_and_move_into_the_inbox_with_keys_in_creation_order(
    database: sqlalchemy.Engine,
) -> None:
    ids = with_existing_tasks(database)
    before = rows(
        database,
        "SELECT id, title, status, created_by, created_at, updated_at, completed_at "
        "FROM tasks ORDER BY title",
    )

    migrate(database, "upgrade", "head")

    after = rows(
        database,
        "SELECT id, title, status, created_by, created_at, updated_at, completed_at "
        "FROM tasks ORDER BY title",
    )
    assert after == before
    assert rows(
        database, "SELECT id, project_id, key, priority, importance FROM tasks ORDER BY key"
    ) == [
        (ids["first"], INBOX, "IN-01", 2, 50),
        (ids["second"], INBOX, "IN-02", 2, 50),
        (ids["third"], INBOX, "IN-03", 2, 50),
    ]
    assert rows(database, "SELECT next_task_number FROM projects") == [(4,)]


def test_the_database_accepts_the_fourth_status_and_still_guards_the_vocabulary(
    database: sqlalchemy.Engine,
) -> None:
    ids = with_existing_tasks(database)
    migrate(database, "upgrade", "head")
    set_status = sqlalchemy.text("UPDATE tasks SET status = :status WHERE id = :id")

    with database.begin() as connection:
        connection.execute(set_status, {"status": "testing", "id": ids["first"]})
    with pytest.raises(sqlalchemy.exc.IntegrityError), database.begin() as connection:
        connection.execute(set_status, {"status": "blocked", "id": ids["first"]})
    with pytest.raises(sqlalchemy.exc.IntegrityError), database.begin() as connection:
        # completed_at still follows status: "testing" is open, so it cannot be completed.
        connection.execute(set_status, {"status": "testing", "id": ids["second"]})


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE tasks SET priority = 4",
        "UPDATE tasks SET priority = -1",
        "UPDATE tasks SET importance = 101",
        "UPDATE tasks SET importance = -1",
        "UPDATE tasks SET key = 'IN-01'",
        "UPDATE tasks SET project_id = gen_random_uuid()",
        "UPDATE projects SET key = 'in'",
        "UPDATE projects SET next_task_number = 0",
        "INSERT INTO projects (id, name, key, next_task_number, created_at, updated_at) "
        "VALUES (gen_random_uuid(), 'Again', 'IN', 1, now(), now())",
        "DELETE FROM projects",
    ],
)
def test_the_database_itself_refuses_what_the_domain_refuses(
    database: sqlalchemy.Engine, change: str
) -> None:
    with_existing_tasks(database)
    migrate(database, "upgrade", "head")

    with pytest.raises(sqlalchemy.exc.IntegrityError), database.begin() as connection:
        connection.execute(sqlalchemy.text(change))


def test_users_gain_an_empty_role_label(database: sqlalchemy.Engine) -> None:
    with_existing_tasks(database)

    migrate(database, "upgrade", "head")

    assert rows(database, "SELECT role_label FROM users") == [(None,)]


def test_the_listing_indexes_exist(database: sqlalchemy.Engine) -> None:
    migrate(database, "upgrade", "head")

    indexes = {
        index["name"]: (index["column_names"], index["dialect_options"].get("postgresql_where"))
        for index in sqlalchemy.inspect(database).get_indexes("tasks")
    }

    assert indexes["ix_tasks_project_id"][0] == ["project_id"]
    assert indexes["ix_tasks_updated_at"][0] == ["updated_at"]
    open_columns, open_where = indexes["ix_tasks_open_project_id_due_date"]
    assert open_columns == ["project_id", "due_date"]
    assert "done" in str(open_where)
    unique = {u["name"] for u in sqlalchemy.inspect(database).get_unique_constraints("tasks")}
    assert "uq_tasks_key" in unique


def test_downgrade_restores_the_previous_schema_and_folds_testing_into_in_progress(
    database: sqlalchemy.Engine,
) -> None:
    ids = with_existing_tasks(database)
    migrate(database, "upgrade", "head")
    with database.begin() as connection:
        connection.execute(
            sqlalchemy.text("UPDATE tasks SET status = 'testing' WHERE id = :id"),
            {"id": ids["third"]},
        )

    migrate(database, "downgrade", PREVIOUS_HEAD)

    inspector = sqlalchemy.inspect(database)
    assert "projects" not in inspector.get_table_names()
    assert {column["name"] for column in inspector.get_columns("tasks")} == {
        "id", "title", "description", "status", "due_date", "created_by", "assignee_id",
        "created_at", "updated_at", "completed_at",
    }  # fmt: skip
    assert "role_label" not in {column["name"] for column in inspector.get_columns("users")}
    assert rows(database, "SELECT title, status FROM tasks ORDER BY title") == [
        ("first", "in_progress"),
        ("second", "done"),
        ("third", "in_progress"),
    ]
    with pytest.raises(sqlalchemy.exc.IntegrityError), database.begin() as connection:
        connection.execute(sqlalchemy.text("UPDATE tasks SET status = 'testing'"))

    migrate(database, "upgrade", "head")

    assert rows(database, "SELECT key FROM tasks ORDER BY key") == [
        ("IN-01",), ("IN-02",), ("IN-03",),
    ]  # fmt: skip
