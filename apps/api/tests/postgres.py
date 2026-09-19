"""Throwaway PostgreSQL databases for the integration tests.

The tests never touch the data of the configured database: each helper works in a
database created next to it (same server, from ``DATABASE__URL``) and dropped afterwards.
"""

import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import TypedDict

import sqlalchemy
from alembic import command
from alembic.config import Config

from app.infrastructure.config.settings import Settings

API_ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def temporary_database() -> Iterator[str]:
    """Create an empty database, yield its URL, drop it."""
    server_url = sqlalchemy.make_url(Settings().database.url)
    name = f"test_{uuid.uuid4().hex}"
    admin = sqlalchemy.create_engine(server_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(sqlalchemy.text(f'CREATE DATABASE "{name}"'))
        try:
            yield server_url.set(database=name).render_as_string(hide_password=False)
        finally:
            with admin.connect() as connection:
                connection.execute(sqlalchemy.text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()


def run_alembic(database_url: str, action: str, revision: str) -> None:
    """``alembic <action> <revision>`` against ``database_url``.

    migrations/env.py drives an async engine with ``asyncio.run``, which cannot start
    inside the event loop of an async test, so the command runs in a worker thread.
    """
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(getattr(command, action), config, revision).result()


INSERT_USER = sqlalchemy.text(
    "INSERT INTO users (id, email, full_name, hashed_password, is_active, created_at) "
    "VALUES (:id, :email, 'Grace Hopper', 'not-a-real-hash', :is_active, now())"
)


class UserRow(TypedDict):
    id: uuid.UUID
    email: str
    is_active: bool


def user_row(*, is_active: bool = True) -> UserRow:
    """Parameters for ``INSERT_USER``: tasks reference users, so a test that writes a task
    row by hand needs somebody to have created it."""
    user_id = uuid.uuid4()
    return {"id": user_id, "email": f"{user_id.hex}@example.com", "is_active": is_active}
