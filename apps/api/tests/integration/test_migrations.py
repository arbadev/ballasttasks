"""Alembic is the only way tables arrive: prove it from an empty database."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
import sqlalchemy
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

import app.infrastructure.db.models  # noqa: F401  (registers the tables on Base.metadata)
from app.infrastructure.db.base import Base
from tests.postgres import (
    INSERT_USER,
    TASK_PROJECT_COLUMNS,
    TASK_PROJECT_VALUES,
    run_alembic,
    temporary_database,
    user_row,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def empty_database() -> Iterator[sqlalchemy.Engine]:
    with temporary_database() as database_url:
        engine = sqlalchemy.create_engine(database_url)
        yield engine
        engine.dispose()


def upgrade(engine: sqlalchemy.Engine, revision: str = "head") -> None:
    run_alembic(engine.url.render_as_string(hide_password=False), "upgrade", revision)


def test_upgrade_head_from_empty_creates_exactly_what_the_orm_models_describe(
    empty_database: sqlalchemy.Engine,
) -> None:
    upgrade(empty_database)

    with empty_database.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    assert differences == []


def test_tasks_table_has_the_columns_and_the_filtering_indexes(
    empty_database: sqlalchemy.Engine,
) -> None:
    upgrade(empty_database)

    inspector = sqlalchemy.inspect(empty_database)
    columns = {column["name"]: column for column in inspector.get_columns("tasks")}
    assert set(columns) == {
        "id",
        "title",
        "description",
        "status",
        "due_date",
        "created_by",
        "assignee_id",
        "created_at",
        "updated_at",
        "completed_at",
        "project_id",
        "key",
        "priority",
        "importance",
    }
    nullable = {name for name, column in columns.items() if column["nullable"]}
    assert nullable == {"description", "due_date", "assignee_id", "completed_at"}
    assert inspector.get_pk_constraint("tasks")["constrained_columns"] == ["id"]
    indexed = {tuple(index["column_names"]) for index in inspector.get_indexes("tasks")}
    assert {("status",), ("due_date",), ("project_id",), ("updated_at",)} <= indexed


def test_the_database_rejects_a_status_outside_the_vocabulary(
    empty_database: sqlalchemy.Engine,
) -> None:
    upgrade(empty_database)

    creator = user_row()
    insert = sqlalchemy.text(
        "INSERT INTO tasks (id, title, status, created_by, created_at, updated_at, "
        f"{TASK_PROJECT_COLUMNS}) "
        "VALUES (gen_random_uuid(), 't', :status, :created_by, now(), now(), "
        f"{TASK_PROJECT_VALUES})"
    )
    with empty_database.begin() as connection:
        connection.execute(INSERT_USER, creator)
        connection.execute(insert, {"status": "todo", "created_by": creator["id"]})
    with (
        pytest.raises(sqlalchemy.exc.IntegrityError) as error,
        empty_database.begin() as connection,
    ):
        connection.execute(insert, {"status": "archived", "created_by": creator["id"]})
    assert "ck_tasks_status" in str(error.value)


@pytest.mark.parametrize(
    ("status", "completed_at"),
    [
        pytest.param("in_progress", datetime(2026, 1, 5, tzinfo=UTC), id="completed, not done"),
        pytest.param("done", None, id="done, not completed"),
    ],
)
def test_the_database_rejects_a_completed_at_that_does_not_follow_the_status(
    empty_database: sqlalchemy.Engine, status: str, completed_at: datetime | None
) -> None:
    upgrade(empty_database)

    creator = user_row()
    insert = sqlalchemy.text(
        "INSERT INTO tasks (id, title, status, created_by, created_at, updated_at, completed_at, "
        f"{TASK_PROJECT_COLUMNS}) "
        "VALUES (gen_random_uuid(), 't', :status, :created_by, now(), now(), "
        f"CAST(:completed_at AS timestamptz), {TASK_PROJECT_VALUES})"
    )
    by = {"created_by": creator["id"]}
    with empty_database.begin() as connection:
        connection.execute(INSERT_USER, creator)
        connection.execute(insert, by | {"status": "done", "completed_at": datetime.now(UTC)})
        connection.execute(insert, by | {"status": "todo", "completed_at": None})
    with (
        pytest.raises(sqlalchemy.exc.IntegrityError) as error,
        empty_database.begin() as connection,
    ):
        connection.execute(insert, by | {"status": status, "completed_at": completed_at})
    assert "ck_tasks_completed_at_follows_status" in str(error.value)


def test_downgrade_to_base_removes_the_tables(empty_database: sqlalchemy.Engine) -> None:
    upgrade(empty_database)

    run_alembic(empty_database.url.render_as_string(hide_password=False), "downgrade", "base")

    assert sqlalchemy.inspect(empty_database).get_table_names() == ["alembic_version"]
