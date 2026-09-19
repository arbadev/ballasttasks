"""Alembic is the only way tables arrive: prove it from an empty database."""

from collections.abc import Iterator

import app.infrastructure.db.models  # noqa: F401  (registers the tables on Base.metadata)
import pytest
import sqlalchemy
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.infrastructure.db.base import Base
from tests.postgres import run_alembic, temporary_database

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
    }
    nullable = {name for name, column in columns.items() if column["nullable"]}
    assert nullable == {"description", "due_date", "assignee_id", "completed_at"}
    assert inspector.get_pk_constraint("tasks")["constrained_columns"] == ["id"]
    indexed = {tuple(index["column_names"]) for index in inspector.get_indexes("tasks")}
    assert {("status",), ("due_date",)} <= indexed


def test_the_database_rejects_a_status_outside_the_vocabulary(
    empty_database: sqlalchemy.Engine,
) -> None:
    upgrade(empty_database)

    insert = sqlalchemy.text(
        "INSERT INTO tasks (id, title, status, created_by, created_at, updated_at) "
        "VALUES (gen_random_uuid(), 't', :status, gen_random_uuid(), now(), now())"
    )
    with empty_database.begin() as connection:
        connection.execute(insert, {"status": "todo"})
    with pytest.raises(sqlalchemy.exc.IntegrityError), empty_database.begin() as connection:
        connection.execute(insert, {"status": "archived"})


def test_downgrade_to_base_removes_the_tables(empty_database: sqlalchemy.Engine) -> None:
    upgrade(empty_database)

    run_alembic(empty_database.url.render_as_string(hide_password=False), "downgrade", "base")

    assert sqlalchemy.inspect(empty_database).get_table_names() == ["alembic_version"]
