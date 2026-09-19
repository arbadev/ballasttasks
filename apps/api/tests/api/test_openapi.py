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
    assert schemas["TaskStatus"]["enum"] == ["todo", "in_progress", "testing", "done"]
    assert schemas["TaskListResponse"]["required"] == ["items", "total", "limit", "offset"]
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
    assert documented("/tasks", "post") == {
        "201": "TaskResponse",
        "401": error,
        "422": invalid,
        "429": error,
    }
    assert documented("/tasks", "get") == {
        "200": "TaskListResponse",
        "401": error,
        "422": invalid,
        "429": error,
    }
    # One task is read with its steps; a change answers like the list, without them.
    for method, model in (("get", "TaskDetailResponse"), ("patch", "TaskResponse")):
        assert documented("/tasks/{id_or_key}", method) == {
            "200": model,
            "401": error,
            "404": error,
            "422": invalid,
            "429": error,
        }
    assert documented("/tasks/{id_or_key}", "delete") == {
        "204": None,
        "401": error,
        "404": error,
        "422": invalid,
        "429": error,
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
        "initials",
        "role_label",
    }
    assert components["TokenResponse"]["properties"]["token_type"]["const"] == "bearer"
    assert components["RegisterRequest"]["properties"]["password"]["writeOnly"] is True

    error = {"$ref": "#/components/schemas/ErrorResponse"}
    register = schema["paths"]["/auth/register"]["post"]["responses"]
    login = schema["paths"]["/auth/login"]["post"]["responses"]
    me = schema["paths"]["/auth/me"]["get"]["responses"]
    assert set(register) == {"201", "409", "422", "429"}
    assert set(login) == {"200", "401", "422", "429"}
    assert set(me) == {"200", "401", "429"}
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

    assert set(providers) == {"200", "429"}
    assert set(start) == {"303", "404", "422", "429"}
    assert set(callback) == {"303", "404", "422", "429"}
    assert set(exchange) == {"200", "401", "422", "429"}
    for redirect in (start["303"], callback["303"]):
        assert "Location" in redirect["headers"]
        assert "content" not in redirect
    assert start["404"]["content"]["application/json"]["schema"] == error
    assert callback["404"]["content"]["application/json"]["schema"] == error
    assert exchange["401"]["content"]["application/json"]["schema"] == error
    assert exchange["200"]["content"]["application/json"]["schema"] == token
    # The routes that present a credential of their own take no bearer token at all. The
    # other two are public as well; the general rate limiter merely reads an optional bearer
    # there, so that a signed-in caller spends their own budget.
    for path in ("/auth/sso/{provider}/callback", "/auth/sso/exchange"):
        assert "security" not in next(iter(schema["paths"][path].values()))


async def test_openapi_documents_the_design_model(client: httpx.AsyncClient) -> None:
    document = (await client.get("/openapi.json")).json()
    schemas, paths = document["components"]["schemas"], document["paths"]

    assert {
        "AttentionResponse",
        "PeopleResponse",
        "PersonResponse",
        "ProfileUpdate",
        "ProjectCreate",
        "ProjectListResponse",
        "ProjectResponse",
        "ProjectUpdate",
        "SignalCountsResponse",
        "TaskCountsResponse",
        "TaskPriority",
        "TaskSummaryResponse",
    } <= set(schemas)
    assert schemas["TaskPriority"]["enum"] == ["P0", "P1", "P2", "P3"]
    reasons = schemas["AttentionResponse"]["properties"]["reasons"]
    assert reasons["items"] == {"$ref": "#/components/schemas/AttentionReason"}
    assert schemas["AttentionReason"]["enum"] == [
        "overdue",
        "p0_at_risk",
        "due_today",
        "due_soon",
        "needs_owner",
    ]
    assert {"attention", "key", "project_id", "priority", "importance"} <= set(
        schemas["TaskResponse"]["required"]
    )
    importance = schemas["TaskCreate"]["properties"]["importance"]
    assert (importance["minimum"], importance["maximum"], importance["default"]) == (0, 100, 50)
    assert "email" not in schemas["PersonResponse"]["properties"]
    assert "key" not in schemas["ProjectUpdate"]["properties"]
    assert "key" not in schemas["TaskUpdate"]["properties"]
    assert "/tasks/{task_id}" not in paths
    assert set(paths["/projects"]) == {"get", "post"}
    assert set(paths["/projects/{project_id}"]) == {"get", "patch"}
    assert set(paths["/users"]) == {"get"}
    assert set(paths["/auth/me"]) == {"get", "patch"}


async def test_openapi_documents_every_new_response(client: httpx.AsyncClient) -> None:
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
    assert documented("/tasks/summary", "get") == {
        "200": "TaskSummaryResponse",
        "401": error,
        "422": invalid,
        "429": error,
    }
    assert documented("/projects", "get") == {
        "200": "ProjectListResponse",
        "401": error,
        "429": error,
    }
    assert documented("/projects", "post") == {
        "201": "ProjectResponse",
        "401": error,
        "409": error,
        "422": invalid,
        "429": error,
    }
    for method in ("get", "patch"):
        assert documented("/projects/{project_id}", method) == {
            "200": "ProjectResponse",
            "401": error,
            "404": error,
            "422": invalid,
            "429": error,
        }
    assert documented("/users", "get") == {"200": "PeopleResponse", "401": error, "429": error}
    assert documented("/auth/me", "patch") == {
        "200": "UserResponse",
        "401": error,
        "422": invalid,
        "429": error,
    }


async def test_openapi_documents_the_list_parameters(client: httpx.AsyncClient) -> None:
    paths = (await client.get("/openapi.json")).json()["paths"]
    parameters = {p["name"]: p for p in paths["/tasks"]["get"]["parameters"]}
    summary = {p["name"] for p in paths["/tasks/summary"]["get"]["parameters"]}

    assert set(parameters) == {
        "scope", "project_id", "status", "due", "due_before", "due_after", "priority",
        "assignee_id", "q", "signal", "sort", "limit", "offset",
    }  # fmt: skip
    assert summary == set(parameters) - {"sort", "limit", "offset"}
    limit = parameters["limit"]["schema"]
    assert (limit["default"], limit["minimum"], limit["maximum"]) == (50, 1, 200)
    assert parameters["sort"]["schema"]["default"] == "urgency"
    assert all(parameter["description"] for parameter in parameters.values())


async def test_openapi_documents_every_step_comment_and_activity_response(
    client: httpx.AsyncClient,
) -> None:
    schema = (await client.get("/openapi.json")).json()
    paths, schemas = schema["paths"], schema["components"]["schemas"]

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

    errors = {"401": "ErrorResponse", "404": "ErrorResponse", "429": "ErrorResponse"}
    refused = errors | {"422": "HTTPValidationError"}
    assert documented("/tasks/{id_or_key}/steps", "get") == {"200": "StepListResponse"} | refused
    assert documented("/tasks/{id_or_key}/steps", "post") == {"201": "StepResponse"} | refused
    assert (
        documented("/tasks/{id_or_key}/steps/bulk", "post") == {"201": "StepListResponse"} | refused
    )
    assert (
        documented("/tasks/{id_or_key}/steps/order", "put") == {"200": "StepListResponse"} | refused
    )
    assert (
        documented("/tasks/{id_or_key}/steps/{step_id}", "patch")
        == {"200": "StepResponse"} | refused
    )
    assert documented("/tasks/{id_or_key}/steps/{step_id}", "delete") == {"204": None} | refused
    assert (
        documented("/tasks/{id_or_key}/comments", "post")
        == {"201": "ActivityEntryResponse"} | refused
    )
    assert (
        documented("/tasks/{id_or_key}/activity", "get")
        == {"200": "ActivityListResponse"} | refused
    )

    assert set(schemas["StepResponse"]["properties"]) == {
        "id",
        "task_id",
        "title",
        "done",
        "position",
        "created_at",
    }
    assert set(schemas["ActivityEntryResponse"]["properties"]) == {
        "id",
        "task_id",
        "kind",
        "text",
        "actor",
        "created_at",
    }
    assert set(schemas["ActorResponse"]["properties"]) == {"id", "full_name", "initials"}
    assert schemas["ActivityKind"]["enum"] == ["log", "comment"]
    assert {"steps_total", "steps_done", "comments_count"} <= set(
        schemas["TaskResponse"]["required"]
    )
    assert set(schemas["TaskDetailResponse"]["properties"]) == set(
        schemas["TaskResponse"]["properties"]
    ) | {"steps"}
    assert schemas["StepsCreate"]["properties"]["titles"]["maxItems"] == 20
    assert schemas["StepsCreate"]["properties"]["titles"]["minItems"] == 1
