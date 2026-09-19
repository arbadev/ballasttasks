import os
from collections.abc import Iterator

import pytest

from tests.postgres import run_alembic, temporary_database

# Closed local port: connections are refused immediately, so "service down" is fast and offline.
DOWN_DATABASE_URL = "postgresql+psycopg://user:pass@127.0.0.1:1/down"
DOWN_REDIS_URL = "redis://127.0.0.1:1/0"

# Test-only signing key: 64 bytes, so it is long enough for every supported HMAC algorithm.
TEST_JWT_SECRET = "test-only-jwt-secret-" + "t" * 44

SETTINGS_ENV_PREFIXES = (
    "APP__",
    "DATABASE__",
    "REDIS__",
    "AI__",
    "CORS__",
    "AUTH__",
    "RATE_LIMIT__",
    "SSO__",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Environment with no settings variables, whatever the developer has exported."""
    for key in list(os.environ):
        if key.startswith(SETTINGS_ENV_PREFIXES):
            monkeypatch.delenv(key)
    return monkeypatch


@pytest.fixture
def minimal_env(clean_env: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Only the required variables, pointing at services that are down."""
    clean_env.setenv("DATABASE__URL", DOWN_DATABASE_URL)
    clean_env.setenv("REDIS__URL", DOWN_REDIS_URL)
    clean_env.setenv("AUTH__JWT_SECRET", TEST_JWT_SECRET)
    return clean_env


@pytest.fixture(scope="session")
def migrated_database_url() -> Iterator[str]:
    """A throwaway database brought from empty to ``alembic upgrade head`` (integration)."""
    with temporary_database() as database_url:
        run_alembic(database_url, "upgrade", "head")
        yield database_url
