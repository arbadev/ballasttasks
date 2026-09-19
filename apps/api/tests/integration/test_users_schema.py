"""The ``users`` migration, proven against real PostgreSQL from an empty database."""

import app.infrastructure.db.models  # noqa: F401  (registers every model on Base.metadata)
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.infrastructure.db.base import Base
from tests.support.database import alembic_config, scratch_database

pytestmark = pytest.mark.integration

INSERT_USER = text(
    "INSERT INTO users (id, email, full_name, hashed_password, is_active, created_at) "
    "VALUES (gen_random_uuid(), :email, 'Ada', 'hash', true, now())"
)


def test_upgrade_head_from_an_empty_database_creates_users(migrated_database_url: str) -> None:
    engine = create_engine(migrated_database_url)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            head = ScriptDirectory.from_config(alembic_config()).get_current_head()

            assert MigrationContext.configure(connection).get_current_revision() == head
            assert "users" in inspector.get_table_names()
            assert {column["name"] for column in inspector.get_columns("users")} == {
                "id",
                "email",
                "full_name",
                "hashed_password",
                "is_active",
                "created_at",
            }
    finally:
        engine.dispose()


def test_the_orm_models_match_the_migrations_exactly(migrated_database_url: str) -> None:
    engine = create_engine(migrated_database_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})

            assert compare_metadata(context, Base.metadata) == []
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


def test_downgrade_to_base_removes_users_again() -> None:
    with scratch_database() as url:
        command.downgrade(alembic_config(), "base")

        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                assert "users" not in inspect(connection).get_table_names()
        finally:
            engine.dispose()
