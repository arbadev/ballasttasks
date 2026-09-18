"""Run with `uv run pytest -m integration` against real PostgreSQL and Redis.

Connection details come from the same environment variables the app uses
(`DATABASE__URL`, `REDIS__URL`), read through `Settings`.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from celery.contrib.testing.worker import start_worker
from sqlalchemy import text

from app.bootstrap import Container, build_container, load_settings
from app.infrastructure.jobs.factory import create_celery_app
from app.main import create_app

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
async def container() -> AsyncIterator[Container]:
    built = build_container(load_settings())
    yield built
    await built.aclose()


async def test_real_postgresql_and_redis_report_ok(container: Container) -> None:
    report = await container.check_readiness.execute()

    assert {result.name: result.healthy for result in report.results} == {
        "database": True,
        "redis": True,
        "ai": True,
    }


async def test_readiness_endpoint_is_200_against_real_services(container: Container) -> None:
    app = create_app(container=container)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_alembic_baseline_is_applied() -> None:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    baseline = ScriptDirectory.from_config(config).get_current_head()
    assert baseline is not None

    command.upgrade(config, "head")

    assert _current_revision() == baseline


def _current_revision() -> str:
    import asyncio

    async def _read() -> str:
        built = build_container(load_settings())
        try:
            async with built.engine.connect() as connection:
                result = await connection.execute(text("SELECT version_num FROM alembic_version"))
                return str(result.scalar_one())
        finally:
            await built.aclose()

    return asyncio.run(_read())


def test_ping_returns_pong_through_a_real_worker_and_the_redis_broker() -> None:
    url = load_settings().redis.url
    celery_app = create_celery_app(broker_url=url, result_backend=url)

    with start_worker(celery_app, perform_ping_check=False, pool="solo", loglevel="WARNING"):
        result = celery_app.tasks["ping"].delay()
        assert result.get(timeout=30) == "pong"
