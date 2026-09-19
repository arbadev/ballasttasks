from dataclasses import replace

import httpx
import pytest

from app.api.schemas.health import HealthResponse, ReadinessResponse
from app.bootstrap import build_container, load_settings
from app.infrastructure.ai.health import LanguageModelHealthCheck
from app.main import create_app
from tests.ai_stubs import (
    OPENROUTER_KEY_INFO,
    OPENROUTER_MODEL,
    TEST_API_KEY,
    answering,
    openrouter_error,
    openrouter_over,
)
from tests.api.conftest import ClientFactory
from tests.fakes import RaisingHealthCheck, StubHealthCheck


async def test_health_is_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    HealthResponse.model_validate(response.json(), strict=True)


async def test_ready_is_200_with_the_pinned_body_when_every_check_passes(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": [
            {"name": "database", "status": "ok"},
            {"name": "redis", "status": "ok"},
            {"name": "ai", "status": "ok"},
        ],
        "ai": {"provider": "fake", "model": "fake-1"},
    }


async def test_ready_is_503_and_names_the_failing_component(client_with: ClientFactory) -> None:
    checks = [StubHealthCheck("database"), StubHealthCheck("redis", healthy=False)]

    async with client_with(checks) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    body = ReadinessResponse.model_validate(response.json(), strict=True)
    assert body.status == "not_ready"
    assert [(c.name, c.status) for c in body.checks] == [("database", "ok"), ("redis", "failed")]
    assert body.ai.provider == "fake"


async def test_ready_is_503_not_500_when_a_check_raises(client_with: ClientFactory) -> None:
    async with client_with([RaisingHealthCheck("database")]) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == [{"name": "database", "status": "failed"}]


async def test_ready_with_real_adapters_and_services_down_reports_each_component(
    client_with: ClientFactory,
) -> None:
    async with client_with(None) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == [
        {"name": "database", "status": "failed"},
        {"name": "redis", "status": "failed"},
        {"name": "ai", "status": "ok"},
    ]


async def test_ready_reports_a_rejected_ai_key_as_failed_and_still_describes_the_model(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    """A real provider that refuses the key: 503, ``ai`` failed, no crash, no key in the body."""
    model = openrouter_over(answering(401, openrouter_error(401, "Missing Authentication header")))
    container = replace(
        build_container(load_settings()),
        language_model=model,
        health_checks=(
            StubHealthCheck("database"),
            StubHealthCheck("redis"),
            LanguageModelHealthCheck(model, cache_seconds=30),
        ),
    )
    app = create_app(container=container)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": [
            {"name": "database", "status": "ok"},
            {"name": "redis", "status": "ok"},
            {"name": "ai", "status": "failed"},
        ],
        "ai": {"provider": "openrouter", "model": OPENROUTER_MODEL},
    }
    assert TEST_API_KEY not in response.text


async def test_hammering_the_public_ready_endpoint_reaches_the_ai_provider_once(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    upstream_calls: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        upstream_calls.append(request)
        return httpx.Response(200, json=OPENROUTER_KEY_INFO)

    model = openrouter_over(upstream)
    container = replace(
        build_container(load_settings()),
        language_model=model,
        health_checks=(LanguageModelHealthCheck(model, cache_seconds=30),),
    )
    app = create_app(container=container)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        statuses = [(await client.get("/health/ready")).status_code for _ in range(5)]

    assert statuses == [200] * 5
    assert len(upstream_calls) == 1
