import httpx
import pytest

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


async def test_openapi_documents_the_task_components(client: httpx.AsyncClient) -> None:
    schemas = (await client.get("/openapi.json")).json()["components"]["schemas"]

    assert {
        "TaskCreate",
        "TaskUpdate",
        "TaskResponse",
        "TaskListResponse",
        "TaskStatus",
        "ErrorResponse",
    } <= set(schemas)
    assert schemas["TaskStatus"]["enum"] == ["todo", "in_progress", "done"]
    assert schemas["TaskListResponse"]["required"] == ["items"]
    assert schemas["TaskCreate"]["required"] == ["title"]
    assert "created_by" not in schemas["TaskCreate"]["properties"]
    assert set(schemas["TaskResponse"]["required"]) == set(schemas["TaskResponse"]["properties"])


async def test_openapi_says_title_and_status_cannot_be_null_in_a_patch(
    client: httpx.AsyncClient,
) -> None:
    properties = (await client.get("/openapi.json")).json()["components"]["schemas"]["TaskUpdate"][
        "properties"
    ]

    assert properties["title"]["type"] == "string"
    assert properties["status"]["$ref"] == "#/components/schemas/TaskStatus"
    assert "anyOf" not in properties["status"]
    assert {"type": "null"} in properties["assignee_id"]["anyOf"]


async def test_openapi_documents_every_task_response(client: httpx.AsyncClient) -> None:
    paths = (await client.get("/openapi.json")).json()["paths"]

    def documented(path: str, method: str) -> dict[str, str | None]:
        return {
            code: response.get("content", {})
            .get("application/json", {})
            .get("schema", {})
            .get("$ref", "")
            .rpartition("/")[2]
            or None
            for code, response in paths[path][method]["responses"].items()
        }

    error, invalid = "ErrorResponse", "HTTPValidationError"
    assert documented("/tasks", "post") == {"201": "TaskResponse", "401": error, "422": invalid}
    assert documented("/tasks", "get") == {"200": "TaskListResponse", "401": error}
    for method in ("get", "patch"):
        assert documented("/tasks/{task_id}", method) == {
            "200": "TaskResponse",
            "401": error,
            "404": error,
            "422": invalid,
        }
    assert documented("/tasks/{task_id}", "delete") == {
        "204": None,
        "401": error,
        "404": error,
        "422": invalid,
    }


async def test_openapi_documents_the_auth_contract(client: httpx.AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    components = schema["components"]["schemas"]

    assert {"RegisterRequest", "UserResponse", "TokenResponse", "ErrorResponse"} <= set(components)
    assert set(components["UserResponse"]["properties"]) == {
        "id",
        "email",
        "full_name",
        "is_active",
        "created_at",
    }
    assert components["TokenResponse"]["properties"]["token_type"]["const"] == "bearer"
    assert components["RegisterRequest"]["properties"]["password"]["writeOnly"] is True

    error = {"$ref": "#/components/schemas/ErrorResponse"}
    register = schema["paths"]["/auth/register"]["post"]["responses"]
    login = schema["paths"]["/auth/login"]["post"]["responses"]
    me = schema["paths"]["/auth/me"]["get"]["responses"]
    assert set(register) == {"201", "409", "422"}
    assert set(login) == {"200", "401", "422"}
    assert set(me) == {"200", "401"}
    assert register["409"]["content"]["application/json"]["schema"] == error
    assert login["401"]["content"]["application/json"]["schema"] == error
    assert me["401"]["content"]["application/json"]["schema"] == error


async def test_openapi_wires_swagger_authorize_to_the_login_form(
    client: httpx.AsyncClient,
) -> None:
    schema = (await client.get("/openapi.json")).json()

    flow = schema["components"]["securitySchemes"]["OAuth2PasswordBearer"]["flows"]["password"]
    assert flow["tokenUrl"] == "auth/login"
    assert schema["paths"]["/auth/me"]["get"]["security"] == [{"OAuth2PasswordBearer": []}]
    assert "security" not in schema["paths"]["/health"]["get"]
    assert "security" not in schema["paths"]["/health/ready"]["get"]
    assert "security" not in schema["paths"]["/auth/register"]["post"]


@pytest.mark.parametrize("model", ["TaskCreate", "TaskUpdate"])
async def test_openapi_says_who_a_task_can_be_assigned_to(
    client: httpx.AsyncClient, model: str
) -> None:
    schemas = (await client.get("/openapi.json")).json()["components"]["schemas"]

    assert "active user" in schemas[model]["properties"]["assignee_id"]["description"]


async def test_openapi_documents_the_single_sign_on_contract(client: httpx.AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    components = schema["components"]["schemas"]

    assert {"SsoProvidersResponse", "SsoProvider", "SsoExchangeRequest"} <= set(components)
    assert set(components["SsoProvider"]["properties"]) == {"name"}
    assert components["SsoExchangeRequest"]["properties"]["code"]["writeOnly"] is True
    assert components["SsoExchangeRequest"]["additionalProperties"] is False

    error = {"$ref": "#/components/schemas/ErrorResponse"}
    token = {"$ref": "#/components/schemas/TokenResponse"}
    providers = schema["paths"]["/auth/sso/providers"]["get"]["responses"]
    start = schema["paths"]["/auth/sso/{provider}/start"]["get"]["responses"]
    callback = schema["paths"]["/auth/sso/{provider}/callback"]["get"]["responses"]
    exchange = schema["paths"]["/auth/sso/exchange"]["post"]["responses"]

    assert set(providers) == {"200"}
    assert set(start) == {"303", "404", "422"}
    assert set(callback) == {"303", "404", "422"}
    assert set(exchange) == {"200", "401", "422"}
    for redirect in (start["303"], callback["303"]):
        assert "Location" in redirect["headers"]
        assert "content" not in redirect
    assert start["404"]["content"]["application/json"]["schema"] == error
    assert callback["404"]["content"]["application/json"]["schema"] == error
    assert exchange["401"]["content"]["application/json"]["schema"] == error
    assert exchange["200"]["content"]["application/json"]["schema"] == token
    for path in ("/auth/sso/providers", "/auth/sso/exchange"):
        assert "security" not in next(iter(schema["paths"][path].values()))
