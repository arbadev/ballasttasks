"""The ``users`` migration against real PostgreSQL.

That ``upgrade head`` from empty matches the ORM models, and that ``downgrade base``
removes every table, is proven for all tables at once in ``test_migrations.py``.
"""

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from tests.postgres import API_ROOT

pytestmark = pytest.mark.integration


def _script_directory() -> ScriptDirectory:
    config = Config(str(API_ROOT / "alembic.ini"))
    return ScriptDirectory.from_config(config)


INSERT_USER = text(
    "INSERT INTO users (id, email, full_name, hashed_password, is_active, created_at) "
    "VALUES (gen_random_uuid(), :email, 'Ada', 'hash', true, now())"
)


def test_upgrade_head_from_an_empty_database_creates_users(migrated_database_url: str) -> None:
    engine = create_engine(migrated_database_url)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            head = _script_directory().get_current_head()

            assert MigrationContext.configure(connection).get_current_revision() == head
            assert "users" in inspector.get_table_names()
            assert {column["name"] for column in inspector.get_columns("users")} == {
                "id",
                "email",
                "full_name",
                "hashed_password",
                "is_active",
                "created_at",
                "role_label",
            }
    finally:
        engine.dispose()


def test_the_database_itself_refuses_a_duplicate_email(migrated_database_url: str) -> None:
    engine = create_engine(migrated_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(INSERT_USER, {"email": "constraint@example.com"})
        with pytest.raises(IntegrityError, match="uq_users_email"), engine.begin() as connection:
            connection.execute(INSERT_USER, {"email": "constraint@example.com"})
    finally:
        engine.dispose()


def test_there_is_one_head_and_users_follow_tasks() -> None:
    """One linear history: baseline -> create_tasks -> create_users -> wire_tasks_to_users
    -> add_user_identities."""
    scripts = _script_directory()

    assert len(scripts.get_heads()) == 1
    chain = [revision.doc for revision in scripts.walk_revisions("base", "heads")]
    assert list(reversed(chain)) == [
        "baseline",
        "create tasks",
        "create users",
        "wire tasks to users",
        "design task model",
        "add user identities",
        "create attachments",
    ]
