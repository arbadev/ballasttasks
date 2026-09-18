import httpx

from app.api.schemas.health import HealthResponse, ReadinessResponse
from tests.api.conftest import ClientFactory
from tests.fakes import StubHealthCheck


async def test_openapi_documents_the_pinned_components(client: httpx.AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()

    assert {"HealthResponse", "ReadinessResponse", "ComponentStatus", "AiInfo"} <= set(
        schema["components"]["schemas"]
    )


async def test_openapi_documents_200_and_503_for_readiness(client: httpx.AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()

    responses = schema["paths"]["/health/ready"]["get"]["responses"]
    ref = {"$ref": "#/components/schemas/ReadinessResponse"}
    assert responses["200"]["content"]["application/json"]["schema"] == ref
    assert responses["503"]["content"]["application/json"]["schema"] == ref
    assert set(responses) == {"200", "503"}

    health = schema["paths"]["/health"]["get"]["responses"]
    assert health["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HealthResponse"
    }


async def test_openapi_pins_the_status_vocabularies(client: httpx.AsyncClient) -> None:
    schemas = (await client.get("/openapi.json")).json()["components"]["schemas"]

    assert schemas["HealthResponse"]["properties"]["status"]["const"] == "ok"
    assert schemas["ReadinessResponse"]["properties"]["status"]["enum"] == ["ready", "not_ready"]
    assert schemas["ComponentStatus"]["properties"]["status"]["enum"] == ["ok", "failed"]
    assert set(schemas["ReadinessResponse"]["required"]) == {"status", "checks", "ai"}


async def test_real_responses_conform_to_the_documented_models(client_with: ClientFactory) -> None:
    async with client_with([StubHealthCheck("database")]) as client:
        HealthResponse.model_validate((await client.get("/health")).json(), strict=True)
        ReadinessResponse.model_validate((await client.get("/health/ready")).json(), strict=True)

    async with client_with([StubHealthCheck("database", healthy=False)]) as client:
        ReadinessResponse.model_validate((await client.get("/health/ready")).json(), strict=True)


async def test_swagger_ui_loads(client: httpx.AsyncClient) -> None:
    response = await client.get("/docs")

    assert response.status_code == 200
    assert "swagger-ui" in response.text
