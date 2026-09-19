"""The revision that wires ``tasks`` to ``users``, against real PostgreSQL.

It has to work on a database that already holds tasks, written while ``created_by`` and
``assignee_id`` were plain UUIDs that nothing checked.
"""

import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy

from tests.postgres import INSERT_USER, run_alembic, temporary_database, user_row

pytestmark = pytest.mark.integration

CREATE_USERS = "2dcaf48d517c"

INSERT_TASK = sqlalchemy.text(
    "INSERT INTO tasks (id, title, status, created_by, assignee_id, created_at, updated_at) "
    "VALUES (:id, :title, 'todo', :created_by, :assignee_id, "
    "'2026-01-05T09:00:00+00:00', '2026-01-05T09:00:00+00:00')"
)
TASKS = sqlalchemy.text(
    "SELECT id, title, status, created_by, assignee_id, created_at, updated_at FROM tasks"
)


@pytest.fixture
def database() -> Iterator[sqlalchemy.Engine]:
    with temporary_database() as database_url:
        engine = sqlalchemy.create_engine(database_url)
        yield engine
        engine.dispose()


def migrate(engine: sqlalchemy.Engine, action: str, revision: str) -> None:
    run_alembic(engine.url.render_as_string(hide_password=False), action, revision)


def tasks_by_title(engine: sqlalchemy.Engine) -> dict[str, sqlalchemy.Row[tuple[object, ...]]]:
    with engine.connect() as connection:
        return {row.title: row for row in connection.execute(TASKS)}


def test_tasks_reference_users_with_a_deliberate_on_delete_rule(
    database: sqlalchemy.Engine,
) -> None:
    migrate(database, "upgrade", "head")

    foreign_keys = {
        key["name"]: (
            key["constrained_columns"],
            key["referred_table"],
            key["referred_columns"],
            key["options"].get("ondelete"),
        )
        for key in sqlalchemy.inspect(database).get_foreign_keys("tasks")
    }

    assert foreign_keys == {
        "fk_tasks_created_by_users": (["created_by"], "users", ["id"], "RESTRICT"),
        "fk_tasks_assignee_id_users": (["assignee_id"], "users", ["id"], "SET NULL"),
    }


def test_the_columns_a_user_delete_has_to_search_are_indexed(database: sqlalchemy.Engine) -> None:
    migrate(database, "upgrade", "head")

    indexed = {
        tuple(index["column_names"]) for index in sqlalchemy.inspect(database).get_indexes("tasks")
    }

    assert {("created_by",), ("assignee_id",)} <= indexed


def test_the_database_refuses_a_task_for_a_user_who_does_not_exist(
    database: sqlalchemy.Engine,
) -> None:
    migrate(database, "upgrade", "head")
    creator = user_row()
    with database.begin() as connection:
        connection.execute(INSERT_USER, creator)

    for created_by, assignee_id in ((uuid.uuid4(), None), (creator["id"], uuid.uuid4())):
        with pytest.raises(sqlalchemy.exc.IntegrityError), database.begin() as connection:
            connection.execute(
                INSERT_TASK,
                {
                    "id": uuid.uuid4(),
                    "title": "t",
                    "created_by": created_by,
                    "assignee_id": assignee_id,
                },
            )


def test_deleting_an_assignee_unassigns_the_task_and_deleting_a_creator_is_refused(
    database: sqlalchemy.Engine,
) -> None:
    migrate(database, "upgrade", "head")
    creator, assignee = user_row(), user_row()
    delete_user = sqlalchemy.text("DELETE FROM users WHERE id = :id")
    with database.begin() as connection:
        connection.execute(INSERT_USER, [creator, assignee])
        connection.execute(
            INSERT_TASK,
            {
                "id": uuid.uuid4(),
                "title": "kept",
                "created_by": creator["id"],
                "assignee_id": assignee["id"],
            },
        )

    with database.begin() as connection:
        connection.execute(delete_user, {"id": assignee["id"]})
    with pytest.raises(sqlalchemy.exc.IntegrityError), database.begin() as connection:
        connection.execute(delete_user, {"id": creator["id"]})

    kept = tasks_by_title(database)["kept"]
    assert kept.assignee_id is None
    assert kept.created_by == creator["id"]


def test_upgrade_keeps_every_existing_task_and_repairs_the_ids_that_match_no_user(
    database: sqlalchemy.Engine,
) -> None:
    """Rows written before the foreign keys existed.

    - an assignee who is no user: the task is unassigned (what ``ON DELETE SET NULL`` would
      have done had the key been there when that user went away);
    - a creator who is no user: the task and its ``created_by`` are kept, and an inactive
      placeholder user takes that id, because a task must not lose its creator.
    """
    migrate(database, "upgrade", CREATE_USERS)
    ada = user_row()
    ghost_creator, ghost_assignee = uuid.uuid4(), uuid.uuid4()
    rows = [
        {"title": "all real", "created_by": ada["id"], "assignee_id": ada["id"]},
        {"title": "unassigned", "created_by": ada["id"], "assignee_id": None},
        {"title": "ghost assignee", "created_by": ada["id"], "assignee_id": ghost_assignee},
        {"title": "ghost creator", "created_by": ghost_creator, "assignee_id": ada["id"]},
        {"title": "ghost creator again", "created_by": ghost_creator, "assignee_id": None},
        {"title": "both ghosts", "created_by": ghost_creator, "assignee_id": ghost_assignee},
    ]
    with database.begin() as connection:
        connection.execute(INSERT_USER, ada)
        connection.execute(INSERT_TASK, [{"id": uuid.uuid4(), **row} for row in rows])
    before = tasks_by_title(database)

    migrate(database, "upgrade", "head")

    after = tasks_by_title(database)
    assert set(after) == set(before)
    for title in ("all real", "unassigned", "ghost creator", "ghost creator again"):
        assert after[title] == before[title]
    for title in ("ghost assignee", "both ghosts"):
        assert after[title].assignee_id is None
        assert after[title]._replace(assignee_id=ghost_assignee) == before[title]

    with database.connect() as connection:
        users = {
            row.id: row
            for row in connection.execute(
                sqlalchemy.text(
                    "SELECT id, email, full_name, hashed_password, is_active FROM users"
                )
            )
        }
    assert set(users) == {ada["id"], ghost_creator}
    assert users[ada["id"]].is_active is True
    placeholder = users[ghost_creator]
    assert placeholder.is_active is False
    assert placeholder.email == f"unknown-{ghost_creator}@placeholder.invalid"
    assert not placeholder.hashed_password.startswith("$argon2")


def test_downgrade_drops_the_keys_and_the_placeholders_and_keeps_the_tasks(
    database: sqlalchemy.Engine,
) -> None:
    migrate(database, "upgrade", CREATE_USERS)
    ada, ghost_creator = user_row(), uuid.uuid4()
    with database.begin() as connection:
        connection.execute(INSERT_USER, ada)
        connection.execute(
            INSERT_TASK,
            [
                {"id": uuid.uuid4(), "title": "real", "created_by": ada["id"], "assignee_id": None},
                {
                    "id": uuid.uuid4(),
                    "title": "ghost creator",
                    "created_by": ghost_creator,
                    "assignee_id": None,
                },
            ],
        )
    before = tasks_by_title(database)
    migrate(database, "upgrade", "head")

    migrate(database, "downgrade", CREATE_USERS)

    assert sqlalchemy.inspect(database).get_foreign_keys("tasks") == []
    assert tasks_by_title(database) == before
    with database.connect() as connection:
        user_ids = set(connection.scalars(sqlalchemy.text("SELECT id FROM users")))
    assert user_ids == {ada["id"]}
    migrate(database, "upgrade", "head")  # and the way back up still works
