import uuid

import httpx
import pytest

from app.api.schemas.projects import ProjectListResponse, ProjectResponse
from app.domain.project import DEFAULT_PROJECT_ID
from tests.api.conftest import RecordingRequestScopes


async def create(client: httpx.AsyncClient, **body: object) -> dict[str, object]:
    response = await client.post("/projects", json={"name": "Ballast Tasks", "key": "BT"} | body)
    assert response.status_code == 201, response.text
    created: dict[str, object] = response.json()
    return created


# --- POST /projects --------------------------------------------------------------------------


async def test_create_returns_201_with_the_new_project(task_client: httpx.AsyncClient) -> None:
    response = await task_client.post(
        "/projects", json={"name": "  Ballast Tasks ", "key": "BT", "color": "acc"}
    )

    assert response.status_code == 201
    body = response.json()
    ProjectResponse.model_validate(body)
    uuid.UUID(body["id"])
    assert (body["name"], body["key"], body["color"]) == ("Ballast Tasks", "BT", "acc")
    assert body["open_tasks"] == 0
    assert body["created_at"] == body["updated_at"]


async def test_the_colour_is_optional(task_client: httpx.AsyncClient) -> None:
    assert (await create(task_client))["color"] is None


async def test_a_taken_key_is_409_and_nothing_is_stored(
    task_client: httpx.AsyncClient, request_scopes: RecordingRequestScopes
) -> None:
    await create(task_client)

    response = await task_client.post("/projects", json={"name": "Better Tasks", "key": "BT"})
    inbox_again = await task_client.post("/projects", json={"name": "Incoming", "key": "IN"})

    assert response.status_code == 409
    assert response.json() == {"detail": "Project key 'BT' is already taken"}
    assert inbox_again.status_code == 409
    assert request_scopes.events[-1] == "rollback"
    names = [p["name"] for p in (await task_client.get("/projects")).json()["items"]]
    assert names == ["Ballast Tasks", "Inbox"]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"key": "BT"}, id="name missing"),
        pytest.param({"name": "Ballast"}, id="key missing"),
        pytest.param({"name": "", "key": "BT"}, id="name empty"),
        pytest.param({"name": "   ", "key": "BT"}, id="name blank"),
        pytest.param({"name": "x" * 101, "key": "BT"}, id="name too long"),
        pytest.param({"name": "nul\x00", "key": "BT"}, id="name with NUL"),
        pytest.param({"name": "Ballast", "key": "B"}, id="key too short"),
        pytest.param({"name": "Ballast", "key": "ABCDEF"}, id="key too long"),
        pytest.param({"name": "Ballast", "key": "bt"}, id="key lower case"),
        pytest.param({"name": "Ballast", "key": "B1"}, id="key with a digit"),
        pytest.param({"name": "Ballast", "key": "BT", "color": "var(--acc)"}, id="colour css"),
        pytest.param({"name": "Ballast", "key": "BT", "id": str(uuid.uuid4())}, id="unknown field"),
    ],
)
async def test_create_rejects_an_invalid_body(
    task_client: httpx.AsyncClient, body: dict[str, object]
) -> None:
    response = await task_client.post("/projects", json=body)

    assert response.status_code == 422
    detail = response.json()["detail"][0]
    assert {"type", "loc", "msg"} <= set(detail)
    assert "input" not in detail
    assert len((await task_client.get("/projects")).json()["items"]) == 1


# --- GET /projects, GET /projects/{id} ---------------------------------------------------------


async def test_every_workspace_has_the_inbox(task_client: httpx.AsyncClient) -> None:
    response = await task_client.get("/projects")

    assert response.status_code == 200
    body = response.json()
    ProjectListResponse.model_validate(body)
    assert [(p["id"], p["name"], p["key"]) for p in body["items"]] == [
        (str(DEFAULT_PROJECT_ID), "Inbox", "IN")
    ]


async def test_projects_are_listed_by_name_with_their_open_task_counts(
    task_client: httpx.AsyncClient,
) -> None:
    ballast = await create(task_client)
    for status in ("todo", "testing", "done"):
        await task_client.post(
            "/tasks", json={"title": status, "project_id": ballast["id"], "status": status}
        )

    listed = (await task_client.get("/projects")).json()["items"]
    one = await task_client.get(f"/projects/{ballast['id']}")

    assert [(p["key"], p["open_tasks"]) for p in listed] == [("BT", 2), ("IN", 0)]
    assert one.status_code == 200
    assert one.json() == ballast | {"open_tasks": 2}


async def test_an_unknown_project_is_404_and_a_malformed_id_is_422(
    task_client: httpx.AsyncClient,
) -> None:
    project_id = uuid.uuid4()

    unknown = await task_client.get(f"/projects/{project_id}")

    assert unknown.status_code == 404
    assert unknown.json() == {"detail": f"Project {project_id} not found"}
    assert (await task_client.get("/projects/BT")).status_code == 422


# --- PATCH /projects/{id} ------------------------------------------------------------------------


async def test_patch_changes_only_the_given_fields(task_client: httpx.AsyncClient) -> None:
    created = await create(task_client, color="acc")

    renamed = await task_client.patch(f"/projects/{created['id']}", json={"name": "Ballast"})
    cleared = await task_client.patch(f"/projects/{created['id']}", json={"color": None})

    assert renamed.status_code == 200
    assert (renamed.json()["name"], renamed.json()["color"]) == ("Ballast", "acc")
    assert (cleared.json()["name"], cleared.json()["color"]) == ("Ballast", None)
    assert cleared.json()["key"] == "BT"
    assert cleared.json()["updated_at"] >= created["updated_at"]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"name": None}, id="name null"),
        pytest.param({"name": "  "}, id="name blank"),
        pytest.param({"color": "Not A Token"}, id="colour not a token"),
        pytest.param({"key": "NEW"}, id="the key is fixed: tasks carry it"),
    ],
)
async def test_patch_rejects_an_invalid_body_and_leaves_the_project_alone(
    task_client: httpx.AsyncClient, body: dict[str, object]
) -> None:
    created = await create(task_client)

    response = await task_client.patch(f"/projects/{created['id']}", json=body)

    assert response.status_code == 422
    assert (await task_client.get(f"/projects/{created['id']}")).json() == created


async def test_patch_of_an_unknown_project_is_404(task_client: httpx.AsyncClient) -> None:
    response = await task_client.patch(f"/projects/{uuid.uuid4()}", json={"name": "x"})

    assert response.status_code == 404


async def test_projects_cannot_be_deleted(task_client: httpx.AsyncClient) -> None:
    created = await create(task_client)

    assert (await task_client.delete(f"/projects/{created['id']}")).status_code == 405


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/projects"),
        ("POST", "/projects"),
        ("GET", f"/projects/{DEFAULT_PROJECT_ID}"),
        ("PATCH", f"/projects/{DEFAULT_PROJECT_ID}"),
    ],
)
async def test_every_project_route_needs_a_signed_in_user(
    anonymous_client: httpx.AsyncClient, method: str, path: str
) -> None:
    response = await anonymous_client.request(method, path, json={"name": "x", "key": "XX"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}
    assert response.headers["www-authenticate"] == "Bearer"
