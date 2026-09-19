"""The revision that brings attachments, against real PostgreSQL and a database that already
holds tasks: nothing about them changes, they simply have no attachments yet."""

import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy
from sqlalchemy.exc import IntegrityError

from tests.postgres import (
    INSERT_USER,
    TASK_PROJECT_COLUMNS,
    TASK_PROJECT_VALUES,
    run_alembic,
    temporary_database,
    user_row,
)

pytestmark = pytest.mark.integration

PREVIOUS_HEAD = "a1c5e7f90b24"
ATTACHMENTS = "c4a9e7d21b65"

INSERT_TASK = sqlalchemy.text(
    f"INSERT INTO tasks (id, title, status, created_by, created_at, updated_at, "
    f"{TASK_PROJECT_COLUMNS}) VALUES (:id, :title, 'todo', :created_by, "
    f"'2026-01-05T09:00:00+00:00', '2026-01-05T09:00:00+00:00', {TASK_PROJECT_VALUES})"
)
INSERT_ATTACHMENT = sqlalchemy.text(
    "INSERT INTO attachments (id, task_id, kind, name, created_by, created_at, url, "
    "storage_key, content_type, size_bytes) VALUES (:id, :task_id, :kind, :name, :created_by, "
    "now(), :url, :storage_key, :content_type, :size_bytes)"
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


def with_existing_tasks(engine: sqlalchemy.Engine) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """A user and two tasks written at the previous head."""
    migrate(engine, "upgrade", PREVIOUS_HEAD)
    creator = user_row()
    task_ids = [uuid.uuid4(), uuid.uuid4()]
    with engine.begin() as connection:
        connection.execute(INSERT_USER, creator)
        for number, task_id in enumerate(task_ids):
            connection.execute(
                INSERT_TASK, {"id": task_id, "title": f"task {number}", "created_by": creator["id"]}
            )
    return creator["id"], task_ids


def a_link_row(task_id: uuid.UUID, created_by: uuid.UUID, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": uuid.uuid4(),
        "task_id": task_id,
        "kind": "link",
        "name": "The docs",
        "created_by": created_by,
        "url": "https://example.com/docs",
        "storage_key": None,
        "content_type": None,
        "size_bytes": None,
    }
    return row | overrides


def a_file_row(task_id: uuid.UUID, created_by: uuid.UUID, **overrides: object) -> dict[str, object]:
    return (
        a_link_row(
            task_id,
            created_by,
            kind="pdf",
            name="report.pdf",
            url=None,
            storage_key=uuid.uuid4().hex,
            content_type="application/pdf",
            size_bytes=1024,
        )
        | overrides
    )


def test_existing_tasks_are_kept_as_they_are_and_start_with_no_attachments(
    database: sqlalchemy.Engine,
) -> None:
    _, task_ids = with_existing_tasks(database)
    before = rows(database, "SELECT * FROM tasks ORDER BY id")

    migrate(database, "upgrade", ATTACHMENTS)

    assert rows(database, "SELECT * FROM tasks ORDER BY id") == before
    assert len(before) == len(task_ids)
    assert rows(database, "SELECT count(*) FROM attachments") == [(0,)]


def test_existing_tasks_can_be_given_attachments_after_the_upgrade(
    database: sqlalchemy.Engine,
) -> None:
    creator, (task_id, _) = with_existing_tasks(database)
    migrate(database, "upgrade", ATTACHMENTS)

    with database.begin() as connection:
        connection.execute(INSERT_ATTACHMENT, a_link_row(task_id, creator))
        connection.execute(INSERT_ATTACHMENT, a_file_row(task_id, creator))

    assert rows(database, "SELECT kind FROM attachments ORDER BY kind") == [("link",), ("pdf",)]


def test_deleting_a_task_deletes_its_attachment_rows(database: sqlalchemy.Engine) -> None:
    creator, (task_id, other_task_id) = with_existing_tasks(database)
    migrate(database, "upgrade", ATTACHMENTS)
    kept = a_link_row(other_task_id, creator)
    with database.begin() as connection:
        connection.execute(INSERT_ATTACHMENT, a_link_row(task_id, creator))
        connection.execute(INSERT_ATTACHMENT, a_file_row(task_id, creator))
        connection.execute(INSERT_ATTACHMENT, kept)

    with database.begin() as connection:
        connection.execute(sqlalchemy.text("DELETE FROM tasks WHERE id = :id"), {"id": task_id})

    assert rows(database, "SELECT id FROM attachments") == [(kept["id"],)]


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "video"},
        {"kind": "link", "url": None},
        {"kind": "link", "storage_key": "k", "content_type": "application/pdf", "size_bytes": 1},
        {"kind": "pdf", "url": None, "storage_key": None},
        {"kind": "pdf", "url": None, "storage_key": "k", "content_type": None, "size_bytes": 1},
        {"kind": "image", "url": None, "storage_key": "k", "content_type": "image/png"},
        {
            "kind": "image",
            "url": None,
            "storage_key": "k",
            "content_type": "image/png",
            "size_bytes": 0,
        },
        {
            "kind": "pdf",
            "url": "https://example.com",
            "storage_key": "k",
            "content_type": "application/pdf",
            "size_bytes": 1,
        },
    ],
)
def test_a_row_no_attachment_could_be_rebuilt_from_is_refused(
    database: sqlalchemy.Engine, overrides: dict[str, object]
) -> None:
    creator, (task_id, _) = with_existing_tasks(database)
    migrate(database, "upgrade", ATTACHMENTS)

    with pytest.raises(IntegrityError), database.begin() as connection:
        connection.execute(INSERT_ATTACHMENT, a_link_row(task_id, creator) | overrides)


def test_two_attachments_never_share_a_stored_file(database: sqlalchemy.Engine) -> None:
    creator, (task_id, _) = with_existing_tasks(database)
    migrate(database, "upgrade", ATTACHMENTS)
    with database.begin() as connection:
        connection.execute(INSERT_ATTACHMENT, a_file_row(task_id, creator, storage_key="same"))

    with pytest.raises(IntegrityError), database.begin() as connection:
        connection.execute(INSERT_ATTACHMENT, a_file_row(task_id, creator, storage_key="same"))


def test_a_user_who_attached_something_cannot_be_deleted(database: sqlalchemy.Engine) -> None:
    _, (task_id, _) = with_existing_tasks(database)
    migrate(database, "upgrade", ATTACHMENTS)
    somebody = user_row()
    with database.begin() as connection:
        connection.execute(INSERT_USER, somebody)
        connection.execute(INSERT_ATTACHMENT, a_link_row(task_id, somebody["id"]))

    with pytest.raises(IntegrityError), database.begin() as connection:
        connection.execute(
            sqlalchemy.text("DELETE FROM users WHERE id = :id"), {"id": somebody["id"]}
        )


def test_downgrade_drops_the_attachments_and_leaves_the_tasks_alone(
    database: sqlalchemy.Engine,
) -> None:
    creator, (task_id, _) = with_existing_tasks(database)
    before = rows(database, "SELECT * FROM tasks ORDER BY id")
    migrate(database, "upgrade", ATTACHMENTS)
    with database.begin() as connection:
        connection.execute(INSERT_ATTACHMENT, a_link_row(task_id, creator))

    migrate(database, "downgrade", PREVIOUS_HEAD)

    assert rows(database, "SELECT * FROM tasks ORDER BY id") == before
    assert rows(database, "SELECT to_regclass('attachments')") == [(None,)]
    migrate(database, "upgrade", ATTACHMENTS)
    assert rows(database, "SELECT count(*) FROM attachments") == [(0,)]
