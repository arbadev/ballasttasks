import httpx

from app.api.schemas.health import HealthResponse, ReadinessResponse
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
