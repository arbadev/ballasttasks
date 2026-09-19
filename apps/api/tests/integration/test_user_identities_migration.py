"""The revision that adds ``user_identities`` and lets a user have no password.

It has to work on a database that already holds users and tasks: every existing row is
kept exactly as it was (a password user stays a password user and has no identity until
their first single sign-on links one). ``downgrade`` cannot keep "no password" in a NOT
NULL column, so those users get the hash no password matches and keep their tasks.
"""

import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy

from tests.postgres import INSERT_USER, run_alembic, temporary_database, user_row

pytestmark = pytest.mark.integration

PREVIOUS_HEAD = "fa7b13ec7508"

USERS = sqlalchemy.text(
    "SELECT id, email, full_name, hashed_password, is_active, created_at FROM users ORDER BY id"
)
TASKS = sqlalchemy.text("SELECT id, title, created_by, assignee_id FROM tasks ORDER BY id")
INSERT_TASK = sqlalchemy.text(
    "INSERT INTO tasks (id, title, status, created_by, assignee_id, created_at, updated_at) "
    "VALUES (:id, :title, 'todo', :created_by, :assignee_id, now(), now())"
)
INSERT_SSO_USER = sqlalchemy.text(
    "INSERT INTO users (id, email, full_name, hashed_password, is_active, created_at) "
    "VALUES (:id, :email, 'Sso Only', NULL, true, now())"
)
INSERT_IDENTITY = sqlalchemy.text(
    "INSERT INTO user_identities (id, user_id, provider, subject, created_at) "
    "VALUES (gen_random_uuid(), :user_id, :provider, :subject, now())"
)


@pytest.fixture
def database() -> Iterator[sqlalchemy.Engine]:
    with temporary_database() as database_url:
        engine = sqlalchemy.create_engine(database_url)
        yield engine
        engine.dispose()


def migrate(engine: sqlalchemy.Engine, action: str, revision: str) -> None:
    run_alembic(engine.url.render_as_string(hide_password=False), action, revision)


def rows(engine: sqlalchemy.Engine, query: sqlalchemy.TextClause) -> list[tuple[object, ...]]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(query)]


def hashed_password_is_nullable(engine: sqlalchemy.Engine) -> bool:
    columns = {c["name"]: c for c in sqlalchemy.inspect(engine).get_columns("users")}
    return bool(columns["hashed_password"]["nullable"])


def test_upgrade_keeps_every_existing_user_and_task_exactly_as_it_was(
    database: sqlalchemy.Engine,
) -> None:
    migrate(database, "upgrade", PREVIOUS_HEAD)
    ada, grace = user_row(), user_row(is_active=False)
    with database.begin() as connection:
        connection.execute(INSERT_USER, [ada, grace])
        connection.execute(
            INSERT_TASK,
            {"id": uuid.uuid4(), "title": "kept", "created_by": ada["id"], "assignee_id": None},
        )
    users_before, tasks_before = rows(database, USERS), rows(database, TASKS)
    assert not hashed_password_is_nullable(database)

    migrate(database, "upgrade", "head")

    assert rows(database, USERS) == users_before
    assert rows(database, TASKS) == tasks_before
    assert hashed_password_is_nullable(database)
    assert rows(database, sqlalchemy.text("SELECT count(*) FROM user_identities")) == [(0,)]


def test_the_table_has_the_keys_that_make_an_identity_mean_one_user(
    database: sqlalchemy.Engine,
) -> None:
    migrate(database, "upgrade", "head")
    inspector = sqlalchemy.inspect(database)

    columns = {column["name"]: column for column in inspector.get_columns("user_identities")}
    assert set(columns) == {"id", "user_id", "provider", "subject", "created_at"}
    assert not any(column["nullable"] for column in columns.values())
    assert inspector.get_pk_constraint("user_identities")["constrained_columns"] == ["id"]
    assert {
        unique["name"]: unique["column_names"]
        for unique in inspector.get_unique_constraints("user_identities")
    } == {
        "uq_user_identities_provider_subject": ["provider", "subject"],
        "uq_user_identities_user_id_provider": ["user_id", "provider"],
    }
    (foreign_key,) = inspector.get_foreign_keys("user_identities")
    assert foreign_key["name"] == "fk_user_identities_user_id_users"
    assert foreign_key["constrained_columns"] == ["user_id"]
    assert (foreign_key["referred_table"], foreign_key["referred_columns"]) == ("users", ["id"])
    assert foreign_key["options"].get("ondelete") == "CASCADE"


def test_the_database_itself_refuses_a_second_owner_a_second_subject_and_a_ghost(
    database: sqlalchemy.Engine,
) -> None:
    migrate(database, "upgrade", "head")
    ada, grace = user_row(), user_row()
    with database.begin() as connection:
        connection.execute(INSERT_USER, [ada, grace])
        connection.execute(
            INSERT_IDENTITY, {"user_id": ada["id"], "provider": "google", "subject": "sub-1"}
        )

    refused = {
        "uq_user_identities_provider_subject": (grace["id"], "google", "sub-1"),
        "uq_user_identities_user_id_provider": (ada["id"], "google", "sub-2"),
        "fk_user_identities_user_id_users": (uuid.uuid4(), "google", "sub-3"),
    }
    for constraint, (user_id, provider, subject) in refused.items():
        with (
            pytest.raises(sqlalchemy.exc.IntegrityError, match=constraint),
            database.begin() as connection,
        ):
            connection.execute(
                INSERT_IDENTITY, {"user_id": user_id, "provider": provider, "subject": subject}
            )


def test_deleting_a_user_deletes_their_identities(database: sqlalchemy.Engine) -> None:
    migrate(database, "upgrade", "head")
    ada = user_row()
    with database.begin() as connection:
        connection.execute(INSERT_USER, ada)
        connection.execute(
            INSERT_IDENTITY, {"user_id": ada["id"], "provider": "google", "subject": "sub-1"}
        )

    with database.begin() as connection:
        connection.execute(sqlalchemy.text("DELETE FROM users WHERE id = :id"), {"id": ada["id"]})

    assert rows(database, sqlalchemy.text("SELECT count(*) FROM user_identities")) == [(0,)]


def test_downgrade_keeps_every_user_and_task_and_gives_the_passwordless_an_unmatchable_hash(
    database: sqlalchemy.Engine,
) -> None:
    migrate(database, "upgrade", "head")
    ada = user_row()
    sso_only = {"id": uuid.uuid4(), "email": "sso-only@example.com"}
    with database.begin() as connection:
        connection.execute(INSERT_USER, ada)
        connection.execute(INSERT_SSO_USER, sso_only)
        connection.execute(
            INSERT_IDENTITY, {"user_id": sso_only["id"], "provider": "google", "subject": "sub-1"}
        )
        connection.execute(
            INSERT_TASK,
            {
                "id": uuid.uuid4(),
                "title": "created by the sso user",
                "created_by": sso_only["id"],
                "assignee_id": ada["id"],
            },
        )
    tasks_before = rows(database, TASKS)
    users_before = {row[0]: row for row in rows(database, USERS)}

    migrate(database, "downgrade", PREVIOUS_HEAD)

    assert "user_identities" not in sqlalchemy.inspect(database).get_table_names()
    assert not hashed_password_is_nullable(database)
    assert rows(database, TASKS) == tasks_before
    users_after = {row[0]: row for row in rows(database, USERS)}
    assert users_after[ada["id"]] == users_before[ada["id"]]
    downgraded = users_after[sso_only["id"]]
    assert downgraded[3] == "!"  # no Argon2 hash starts like this: no password matches it
    assert downgraded[:3] + downgraded[4:] == (
        users_before[sso_only["id"]][:3] + users_before[sso_only["id"]][4:]
    )

    migrate(database, "upgrade", "head")  # and the way back up still works
    assert hashed_password_is_nullable(database)
