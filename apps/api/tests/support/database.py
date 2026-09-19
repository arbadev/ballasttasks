"""Throwaway PostgreSQL databases for the integration suites.

Each one is created empty next to the configured database, migrated with the project's
own Alembic revisions, and dropped afterwards, so integration tests never read or write
the developer's data and always prove ``alembic upgrade head`` from nothing.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.infrastructure.config.settings import Settings

API_ROOT = Path(__file__).resolve().parents[2]


def alembic_config() -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    return config


@contextmanager
def scratch_database(*, migrate: bool = True) -> Iterator[str]:
    """Yield the URL of a fresh database; ``DATABASE__URL`` points at it meanwhile."""
    base_url = make_url(Settings().database.url)
    name = f"scratch_{uuid.uuid4().hex}"
    url = base_url.set(database=name).render_as_string(hide_password=False)
    admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        with pytest.MonkeyPatch.context() as environment:
            environment.setenv("DATABASE__URL", url)
            if migrate:
                command.upgrade(alembic_config(), "head")
            yield url
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()
