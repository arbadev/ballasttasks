import uuid
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from app.api.schemas.tasks import TaskListResponse, TaskResponse
from app.api.security import get_current_user_id
from app.application.errors import InvalidAssigneeError, StoredTaskInvalid
from app.domain.task import DESCRIPTION_MAX_LENGTH, TITLE_MAX_LENGTH, Task
from tests.api.conftest import USER_ID, AuthFakes, RecordingRequestScopes
from tests.auth_fakes import a_user
from tests.builders import a_task
from tests.fakes import InMemoryTaskRepository

INVALID_ASSIGNEE = {
    "type": "invalid_assignee",
    "loc": ["body", "assignee_id"],
    "msg": "assignee_id must be the id of an active user",
}


async def stored_user(auth_fakes: AuthFakes, *, is_active: bool = True) -> str:
    user = a_user(is_active=is_active)
    await auth_fakes.users.add(user)
    return str(user.id)


async def stored_task_of_a_deactivated_assignee(
    tasks: InMemoryTaskRepository, auth_fakes: AuthFakes
) -> tuple[str, str]:
    """The ids of a task and of its assignee, who was deactivated after being given it."""
    left_the_team = a_user(is_active=False)
    await auth_fakes.users.add(left_the_team)
    task = a_task(USER_ID, assignee_id=left_the_team.id, now=datetime(2026, 1, 5, 9, 0, tzinfo=UTC))
    await tasks.add(task)
    return str(task.id), str(left_the_team.id)


async def create(client: httpx.AsyncClient, **body: object) -> dict[str, object]:
    response = await client.post("/tasks", json={"title": "Write the report"} | body)
    assert response.status_code == 201, response.text
    created: dict[str, object] = response.json()
    return created


# --- POST /tasks ---------------------------------------------------------------------------


async def test_create_returns_201_with_the_new_task(task_client: httpx.AsyncClient) -> None:
    response = await task_client.post("/tasks", json={"title": "Write the report"})

    assert response.status_code == 201
    body = response.json()
    TaskResponse.model_validate(body)
    uuid.UUID(body["id"])
    assert body["title"] == "Write the report"
    assert body["status"] == "todo"
    assert body["description"] is None
    assert body["due_date"] is None
    assert body["assignee_id"] is None
    assert body["completed_at"] is None
    assert body["created_at"] == body["updated_at"]
    assert datetime.fromisoformat(body["created_at"]).utcoffset() is not None


async def test_create_takes_created_by_from_the_authenticated_user(
    task_client: httpx.AsyncClient,
) -> None:
    body = await create(task_client)

    assert body["created_by"] == str(USER_ID)


async def test_create_rejects_created_by_in_the_request_body(
    task_client: httpx.AsyncClient, tasks: InMemoryTaskRepository
) -> None:
    response = await task_client.post(
        "/tasks", json={"title": "Write the report", "created_by": str(uuid.uuid4())}
    )

    assert response.status_code == 422
    assert tasks.all() == []


async def test_create_accepts_the_optional_fields(
    task_client: httpx.AsyncClient, auth_fakes: AuthFakes
) -> None:
    assignee = await stored_user(auth_fakes)

    body = await create(
        task_client, description="Q1 numbers", due_date="2026-02-01", assignee_id=assignee
    )

    assert body["description"] == "Q1 numbers"
    assert body["due_date"] == "2026-02-01"
    assert body["assignee_id"] == assignee


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="title missing"),
        pytest.param({"title": ""}, id="title empty"),
        pytest.param({"title": "   "}, id="title blank (domain rule)"),
        pytest.param({"title": "x" * (TITLE_MAX_LENGTH + 1)}, id="title too long"),
        pytest.param({"title": "t", "description": "x" * (DESCRIPTION_MAX_LENGTH + 1)}, id="desc"),
        pytest.param({"title": "a\x00b"}, id="title with a NUL character"),
        pytest.param({"title": "t", "description": "a\x00b"}, id="description with a NUL"),
        pytest.param({"title": "t", "due_date": "next week"}, id="due_date not a date"),
        pytest.param({"title": "t", "assignee_id": "bob"}, id="assignee_id not a uuid"),
        # The design adds a task straight into a board column, so a status is accepted on
        # create (ADR 0005); one outside the vocabulary is still refused.
        pytest.param({"title": "t", "status": "archived"}, id="status outside the vocabulary"),
    ],
)
async def test_create_answers_422_with_the_validation_error_body(
    task_client: httpx.AsyncClient, tasks: InMemoryTaskRepository, body: dict[str, object]
) -> None:
    response = await task_client.post("/tasks", json=body)

    assert response.status_code == 422
    errors = response.json()["detail"]
    assert isinstance(errors, list)
    assert errors
    assert all({"type", "loc", "msg"} <= set(error) for error in errors)
    assert tasks.all() == []


# --- GET /tasks ----------------------------------------------------------------------------


async def test_list_is_an_envelope_with_an_empty_items_list(
    task_client: httpx.AsyncClient,
) -> None:
    response = await task_client.get("/tasks")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


async def test_list_returns_every_task_newest_first(task_client: httpx.AsyncClient) -> None:
    first = await create(task_client, title="first")
    second = await create(task_client, title="second")

    response = await task_client.get("/tasks")

    TaskListResponse.model_validate(response.json())
    assert response.json() == {"items": [second, first], "total": 2, "limit": 50, "offset": 0}


# --- GET /tasks/{id} -----------------------------------------------------------------------


async def test_get_returns_the_task(task_client: httpx.AsyncClient) -> None:
    created = await create(task_client)

    response = await task_client.get(f"/tasks/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


async def test_any_authenticated_user_can_read_a_task_created_by_someone_else(
    tasks_app: FastAPI, task_client: httpx.AsyncClient
) -> None:
    created = await create(task_client)
    tasks_app.dependency_overrides[get_current_user_id] = uuid.uuid4

    response = await task_client.get(f"/tasks/{created['id']}")

    assert response.status_code == 200
    assert response.json()["created_by"] == str(USER_ID)


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
async def test_an_unknown_id_is_404_with_the_error_body(
    task_client: httpx.AsyncClient, method: str
) -> None:
    task_id = uuid.uuid4()

    response = await task_client.request(method, f"/tasks/{task_id}", json={"title": "x"})

    assert response.status_code == 404
    assert response.json() == {"detail": f"Task {task_id} not found"}


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
async def test_an_id_that_is_not_a_uuid_is_422(task_client: httpx.AsyncClient, method: str) -> None:
    response = await task_client.request(method, "/tasks/42", json={"title": "x"})

    assert response.status_code == 422


# --- PATCH /tasks/{id} ---------------------------------------------------------------------


async def test_patch_changes_only_the_fields_that_were_sent(
    task_client: httpx.AsyncClient,
) -> None:
    created = await create(task_client, description="Q1 numbers", due_date="2026-02-01")

    response = await task_client.patch(
        f"/tasks/{created['id']}", json={"title": "Publish the report"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Publish the report"
    assert body["description"] == "Q1 numbers"
    assert body["due_date"] == "2026-02-01"
    assert body["created_by"] == created["created_by"]
    assert (await task_client.get(f"/tasks/{created['id']}")).json() == body


async def test_patch_marks_a_task_completed_and_reopens_it(
    task_client: httpx.AsyncClient,
) -> None:
    created = await create(task_client)

    done = (await task_client.patch(f"/tasks/{created['id']}", json={"status": "done"})).json()
    assert done["status"] == "done"
    assert done["completed_at"] is not None

    reopened = await task_client.patch(f"/tasks/{created['id']}", json={"status": "in_progress"})
    assert reopened.json()["status"] == "in_progress"
    assert reopened.json()["completed_at"] is None


async def test_patch_assigns_and_unassigns_a_task(
    task_client: httpx.AsyncClient, auth_fakes: AuthFakes
) -> None:
    created = await create(task_client)
    assignee = await stored_user(auth_fakes)

    assigned = await task_client.patch(f"/tasks/{created['id']}", json={"assignee_id": assignee})
    assert assigned.json()["assignee_id"] == assignee

    unassigned = await task_client.patch(f"/tasks/{created['id']}", json={"assignee_id": None})
    assert unassigned.status_code == 200
    assert unassigned.json()["assignee_id"] is None


async def test_patch_with_null_clears_description_and_due_date(
    task_client: httpx.AsyncClient,
) -> None:
    created = await create(task_client, description="Q1 numbers", due_date="2026-02-01")

    response = await task_client.patch(
        f"/tasks/{created['id']}", json={"description": None, "due_date": None}
    )

    assert response.json()["description"] is None
    assert response.json()["due_date"] is None


async def test_patch_with_an_empty_body_changes_nothing(task_client: httpx.AsyncClient) -> None:
    created = await create(task_client)

    response = await task_client.patch(f"/tasks/{created['id']}", json={})

    assert response.status_code == 200
    assert response.json() == created


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"title": None}, id="title cannot be null"),
        pytest.param({"title": "   "}, id="title blank (domain rule)"),
        pytest.param({"title": "x" * (TITLE_MAX_LENGTH + 1)}, id="title too long"),
        pytest.param({"title": "a\x00b"}, id="title with a NUL character"),
        pytest.param({"description": "a\x00b"}, id="description with a NUL character"),
        pytest.param({"status": None}, id="status cannot be null"),
        pytest.param({"status": "archived"}, id="status outside the vocabulary"),
        pytest.param({"assignee_id": "bob"}, id="assignee_id not a uuid"),
        pytest.param({"created_by": str(uuid.uuid4())}, id="created_by cannot change"),
        pytest.param({"status": "done", "title": " "}, id="one bad field rejects the whole patch"),
    ],
)
async def test_patch_answers_422_and_leaves_the_task_unchanged(
    task_client: httpx.AsyncClient, body: dict[str, object]
) -> None:
    created = await create(task_client)

    response = await task_client.patch(f"/tasks/{created['id']}", json=body)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert (await task_client.get(f"/tasks/{created['id']}")).json() == created


async def test_a_stored_task_that_breaks_a_domain_rule_is_a_server_error_not_a_422(
    tasks_app: FastAPI,
    task_client: httpx.AsyncClient,
    tasks: InMemoryTaskRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await create(task_client)

    async def broken_row(task_id: uuid.UUID) -> Task | None:
        raise StoredTaskInvalid(task_id)

    monkeypatch.setattr(tasks, "get", broken_row)
    transport = httpx.ASGITransport(app=tasks_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/tasks/{created['id']}")

    assert response.status_code == 500


# --- assignee_id must be an active user ----------------------------------------------------


@pytest.mark.parametrize("assignee", ["unknown", "inactive"])
async def test_create_answers_422_on_assignee_id_when_the_assignee_is_not_an_active_user(
    task_client: httpx.AsyncClient,
    auth_fakes: AuthFakes,
    request_scopes: RecordingRequestScopes,
    assignee: str,
) -> None:
    assignee_id = (
        str(uuid.uuid4())
        if assignee == "unknown"
        else await stored_user(auth_fakes, is_active=False)
    )

    response = await task_client.post(
        "/tasks", json={"title": "Write the report", "assignee_id": assignee_id}
    )

    assert response.status_code == 422
    assert response.json() == {"detail": [INVALID_ASSIGNEE]}
    assert request_scopes.events == ["begin", "rollback"]
    assert (await task_client.get("/tasks")).json()["items"] == []


@pytest.mark.parametrize("assignee", ["unknown", "inactive"])
async def test_patch_answers_422_on_assignee_id_when_the_assignee_is_not_an_active_user(
    task_client: httpx.AsyncClient, auth_fakes: AuthFakes, assignee: str
) -> None:
    created = await create(task_client)
    assignee_id = (
        str(uuid.uuid4())
        if assignee == "unknown"
        else await stored_user(auth_fakes, is_active=False)
    )

    response = await task_client.patch(
        f"/tasks/{created['id']}", json={"title": "Changed", "assignee_id": assignee_id}
    )

    assert response.status_code == 422
    assert response.json() == {"detail": [INVALID_ASSIGNEE]}
    assert (await task_client.get(f"/tasks/{created['id']}")).json() == created


async def test_patch_accepts_the_deactivated_assignee_the_task_already_has(
    task_client: httpx.AsyncClient, tasks: InMemoryTaskRepository, auth_fakes: AuthFakes
) -> None:
    """A form that saves the whole task names the assignee without changing it."""
    task_id, left_the_team = await stored_task_of_a_deactivated_assignee(tasks, auth_fakes)

    response = await task_client.patch(
        f"/tasks/{task_id}", json={"title": "Changed", "assignee_id": left_the_team}
    )

    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Changed"
    assert response.json()["assignee_id"] == left_the_team
    assert (await task_client.get(f"/tasks/{task_id}")).json() == response.json()


@pytest.mark.parametrize("assignee", ["unknown", "inactive"])
async def test_patch_answers_422_when_a_deactivated_assignee_is_changed_to_somebody_not_active(
    task_client: httpx.AsyncClient,
    tasks: InMemoryTaskRepository,
    auth_fakes: AuthFakes,
    assignee: str,
) -> None:
    task_id, _ = await stored_task_of_a_deactivated_assignee(tasks, auth_fakes)
    before = (await task_client.get(f"/tasks/{task_id}")).json()
    assignee_id = (
        str(uuid.uuid4())
        if assignee == "unknown"
        else await stored_user(auth_fakes, is_active=False)
    )

    response = await task_client.patch(
        f"/tasks/{task_id}", json={"title": "Changed", "assignee_id": assignee_id}
    )

    assert response.status_code == 422
    assert response.json() == {"detail": [INVALID_ASSIGNEE]}
    assert (await task_client.get(f"/tasks/{task_id}")).json() == before


async def test_a_task_can_be_assigned_to_the_user_who_just_registered(
    task_client: httpx.AsyncClient,
) -> None:
    registered = await task_client.post(
        "/auth/register",
        json={"email": "grace@example.com", "full_name": "Grace Hopper", "password": "s3cret-pw!"},
    )
    assert registered.status_code == 201, registered.text

    created = await create(task_client, assignee_id=registered.json()["id"])

    assert created["assignee_id"] == registered.json()["id"]


async def test_an_assignee_the_store_refuses_is_the_same_422_not_a_server_error(
    task_client: httpx.AsyncClient,
    auth_fakes: AuthFakes,
    tasks: InMemoryTaskRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The check passed, then the foreign key said no (the user vanished in between)."""
    assignee = await stored_user(auth_fakes)

    async def refused_by_the_foreign_key(task: Task) -> None:
        assert task.assignee_id is not None
        raise InvalidAssigneeError(task.assignee_id)

    monkeypatch.setattr(tasks, "add", refused_by_the_foreign_key)

    response = await task_client.post("/tasks", json={"title": "t", "assignee_id": assignee})

    assert response.status_code == 422
    assert response.json() == {"detail": [INVALID_ASSIGNEE]}


async def test_the_422_does_not_say_whether_the_id_is_unknown_or_inactive(
    task_client: httpx.AsyncClient, auth_fakes: AuthFakes
) -> None:
    inactive = await stored_user(auth_fakes, is_active=False)

    bodies = [
        (await task_client.post("/tasks", json={"title": "t", "assignee_id": candidate})).json()
        for candidate in (inactive, str(uuid.uuid4()))
    ]

    assert bodies[0] == bodies[1]


# --- DELETE /tasks/{id} --------------------------------------------------------------------


async def test_delete_answers_204_with_no_body_and_the_task_is_gone(
    task_client: httpx.AsyncClient,
) -> None:
    created = await create(task_client)

    response = await task_client.delete(f"/tasks/{created['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert (await task_client.get(f"/tasks/{created['id']}")).status_code == 404


# --- authentication seam -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/tasks"),
        ("GET", "/tasks"),
        ("GET", f"/tasks/{uuid.uuid4()}"),
        ("PATCH", f"/tasks/{uuid.uuid4()}"),
        ("DELETE", f"/tasks/{uuid.uuid4()}"),
    ],
)
async def test_every_task_route_answers_401_without_an_authenticated_user(
    anonymous_client: httpx.AsyncClient,
    request_scopes: RecordingRequestScopes,
    method: str,
    path: str,
) -> None:
    response = await anonymous_client.request(method, path, json={"title": "Write the report"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert request_scopes.tasks.all() == []


# --- unit of work per request --------------------------------------------------------------


async def test_a_successful_request_commits_its_scope_once(
    task_client: httpx.AsyncClient, request_scopes: RecordingRequestScopes
) -> None:
    await create(task_client)

    assert request_scopes.events == ["begin", "commit"]


async def test_a_failed_request_rolls_its_scope_back(
    task_client: httpx.AsyncClient, request_scopes: RecordingRequestScopes
) -> None:
    await task_client.get(f"/tasks/{uuid.uuid4()}")

    assert request_scopes.events == ["begin", "rollback"]


async def test_the_scope_is_committed_before_the_response_starts(
    tasks_app: FastAPI, task_client: httpx.AsyncClient, request_scopes: RecordingRequestScopes
) -> None:
    """A commit that fails must still be able to become an error response."""
    events = request_scopes.events
    body = b'{"title": "Write the report"}'
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/tasks",
        "raw_path": b"/tasks",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json")],
        "client": ("test", 1),
        "server": ("test", 80),
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, object]) -> None:
        events.append(str(message["type"]))

    await tasks_app(scope, receive, send)  # type: ignore[arg-type]

    assert events == ["begin", "commit", "http.response.start", "http.response.body"]
