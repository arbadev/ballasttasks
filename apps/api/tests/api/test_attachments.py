"""Attachments over HTTP: links, what every task representation says about them, removal."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.api.schemas.attachments import AttachmentResponse
from app.api.schemas.tasks import TaskDetailResponse
from app.api.security import get_current_user_id
from app.bootstrap import build_container, load_settings
from app.infrastructure.rate_limit.in_memory_rate_limiter import InMemoryRateLimiter
from app.main import create_app
from tests.api.conftest import ALL_HEALTHY, USER_ID, RecordingRequestScopes
from tests.builders import a_file, a_link, a_task
from tests.fakes import InMemoryAttachmentRepository, InMemoryTaskRepository

NOW = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
LINK = {"url": "https://github.com/arbadev/ballasttasks", "name": "The repository"}


async def create_task(client: httpx.AsyncClient, **body: object) -> dict[str, Any]:
    response = await client.post("/tasks", json={"title": "Write the report"} | body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def attach_link(client: httpx.AsyncClient, task_ref: str, **body: object) -> dict[str, Any]:
    response = await client.post(f"/tasks/{task_ref}/attachments/links", json=LINK | body)
    assert response.status_code == 201, response.text
    attached: dict[str, Any] = response.json()
    return attached


# --- POST /tasks/{id_or_key}/attachments/links ------------------------------------------------


async def test_attaching_a_link_returns_201_with_the_attachment(
    task_client: httpx.AsyncClient, request_scopes: RecordingRequestScopes
) -> None:
    request_scopes.clock = lambda: NOW
    task = await create_task(task_client)

    response = await task_client.post(f"/tasks/{task['id']}/attachments/links", json=LINK)

    assert response.status_code == 201
    body = response.json()
    AttachmentResponse.model_validate(body)
    uuid.UUID(body["id"])
    assert body == {
        "id": body["id"],
        "task_id": task["id"],
        "kind": "link",
        "name": "The repository",
        "url": "https://github.com/arbadev/ballasttasks",
        "content_type": None,
        "size_bytes": None,
        "created_by": str(USER_ID),
        "created_at": "2026-01-05T09:00:00Z",
    }


async def test_a_link_without_a_name_is_named_after_its_host(
    task_client: httpx.AsyncClient,
) -> None:
    task = await create_task(task_client)

    response = await task_client.post(
        f"/tasks/{task['id']}/attachments/links", json={"url": "http://localhost:8000/docs"}
    )

    assert response.status_code == 201
    assert response.json()["name"] == "localhost:8000"


async def test_a_task_is_addressed_by_its_key_too(task_client: httpx.AsyncClient) -> None:
    task = await create_task(task_client)

    attached = await attach_link(task_client, task["key"].lower())

    assert attached["task_id"] == task["id"]


async def test_attaching_touches_the_task(
    task_client: httpx.AsyncClient, request_scopes: RecordingRequestScopes
) -> None:
    task = await create_task(task_client)
    request_scopes.clock = lambda: NOW

    await attach_link(task_client, task["id"])

    assert (await task_client.get(f"/tasks/{task['id']}")).json()["updated_at"] == (
        "2026-01-05T09:00:00Z"
    )


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "/relative",
        "//example.com/x",
        "https://user:secret@example.com/",
        "ftp://example.com",
        "https://example.com/" + "a" * 2000,
    ],
)
async def test_a_url_that_is_not_plain_http_is_422_in_the_standard_body_and_stores_nothing(
    task_client: httpx.AsyncClient, attachments: InMemoryAttachmentRepository, url: str
) -> None:
    task = await create_task(task_client)

    response = await task_client.post(f"/tasks/{task['id']}/attachments/links", json={"url": url})

    assert response.status_code == 422
    (detail,) = response.json()["detail"]
    assert {"type", "loc", "msg"} <= set(detail)
    assert "input" not in detail
    assert detail["loc"][0] == "body"
    assert "secret" not in response.text
    assert attachments.all() == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"url": None},
        {"url": 7},
        {"url": "https://example.com", "name": "x" * 256},
        {"url": "https://example.com", "name": "tab\there"},
        {"url": "https://example.com", "kind": "pdf"},
        {"url": "https://example.com", "created_by": str(uuid.uuid4())},
    ],
)
async def test_a_body_that_is_not_a_link_is_422(
    task_client: httpx.AsyncClient, body: dict[str, object]
) -> None:
    task = await create_task(task_client)

    response = await task_client.post(f"/tasks/{task['id']}/attachments/links", json=body)

    assert response.status_code == 422
    details = response.json()["detail"]
    assert all({"type", "loc", "msg"} <= set(item) and "input" not in item for item in details)


async def test_attaching_to_a_task_that_does_not_exist_is_404(
    task_client: httpx.AsyncClient, attachments: InMemoryAttachmentRepository
) -> None:
    unknown = uuid.uuid4()

    by_id = await task_client.post(f"/tasks/{unknown}/attachments/links", json=LINK)
    by_key = await task_client.post("/tasks/ZZ-99/attachments/links", json=LINK)

    assert (by_id.status_code, by_key.status_code) == (404, 404)
    assert by_id.json() == {"detail": f"Task {unknown} not found"}
    assert attachments.all() == []


async def test_a_reference_that_is_neither_an_id_nor_a_key_is_422(
    task_client: httpx.AsyncClient,
) -> None:
    response = await task_client.post("/tasks/not-a-task/attachments/links", json=LINK)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "id_or_key"]


# --- what the task representations say ------------------------------------------------------


async def test_every_task_representation_counts_its_attachments(
    task_client: httpx.AsyncClient,
) -> None:
    task = await create_task(task_client)
    bare = await create_task(task_client, title="Nothing attached")
    assert task["attachments_count"] == 0

    await attach_link(task_client, task["id"])
    await attach_link(task_client, task["id"], name="Another")

    listed = (await task_client.get("/tasks")).json()["items"]
    assert {item["id"]: item["attachments_count"] for item in listed} == {
        task["id"]: 2,
        bare["id"]: 0,
    }
    patched = await task_client.patch(f"/tasks/{task['id']}", json={"title": "Renamed"})
    assert patched.json()["attachments_count"] == 2
    assert "attachments" not in patched.json()
    assert "attachments" not in listed[0]


async def test_get_returns_the_task_with_its_attachments_oldest_first(
    task_client: httpx.AsyncClient,
    tasks: InMemoryTaskRepository,
    attachments: InMemoryAttachmentRepository,
) -> None:
    task = a_task(USER_ID)
    await tasks.add(task)
    file = a_file(task.id, USER_ID, name="report.pdf", size_bytes=2048)
    await attachments.add(file)
    link = await attach_link(task_client, str(task.id))

    response = await task_client.get(f"/tasks/{task.key}")

    assert response.status_code == 200
    body = response.json()
    TaskDetailResponse.model_validate(body)
    assert body["attachments_count"] == 2
    assert [a["id"] for a in body["attachments"]] == [str(file.id), link["id"]]
    assert body["attachments"][0] == {
        "id": str(file.id),
        "task_id": str(task.id),
        "kind": "pdf",
        "name": "report.pdf",
        "url": None,
        "content_type": "application/pdf",
        "size_bytes": 2048,
        "created_by": str(USER_ID),
        "created_at": "2026-01-05T09:00:00.123456Z",
    }
    # Where the file lives is the server's business.
    assert file.storage_key is not None
    assert file.storage_key not in response.text


# --- DELETE /tasks/{id_or_key}/attachments/{attachment_id} ---------------------------------------


async def test_removing_an_attachment_is_204_and_it_is_gone(
    task_client: httpx.AsyncClient, request_scopes: RecordingRequestScopes
) -> None:
    task = await create_task(task_client)
    link = await attach_link(task_client, task["id"])
    kept = await attach_link(task_client, task["id"], name="Kept")
    request_scopes.clock = lambda: NOW

    response = await task_client.delete(f"/tasks/{task['key']}/attachments/{link['id']}")

    assert response.status_code == 204
    assert response.content == b""
    detail = (await task_client.get(f"/tasks/{task['id']}")).json()
    assert [a["id"] for a in detail["attachments"]] == [kept["id"]]
    assert detail["attachments_count"] == 1
    assert detail["updated_at"] == "2026-01-05T09:00:00Z"


async def test_removing_what_is_not_there_is_404(task_client: httpx.AsyncClient) -> None:
    task = await create_task(task_client)
    other_task = await create_task(task_client)
    link = await attach_link(task_client, other_task["id"])
    unknown = uuid.uuid4()

    not_stored = await task_client.delete(f"/tasks/{task['id']}/attachments/{unknown}")
    of_another_task = await task_client.delete(f"/tasks/{task['id']}/attachments/{link['id']}")
    of_no_task = await task_client.delete(f"/tasks/{uuid.uuid4()}/attachments/{link['id']}")

    assert not_stored.status_code == 404
    assert not_stored.json() == {"detail": f"Attachment {unknown} not found"}
    assert of_another_task.status_code == 404
    assert of_no_task.status_code == 404
    still_there = (await task_client.get(f"/tasks/{other_task['id']}")).json()
    assert still_there["attachments_count"] == 1


async def test_an_attachment_id_that_is_not_a_uuid_is_422(task_client: httpx.AsyncClient) -> None:
    task = await create_task(task_client)

    response = await task_client.delete(f"/tasks/{task['id']}/attachments/first")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "attachment_id"]


async def test_deleting_a_task_deletes_its_attachments(
    task_client: httpx.AsyncClient, attachments: InMemoryAttachmentRepository
) -> None:
    task = await create_task(task_client)
    other_task = await create_task(task_client)
    await attach_link(task_client, task["id"])
    kept = await attach_link(task_client, other_task["id"])

    assert (await task_client.delete(f"/tasks/{task['id']}")).status_code == 204

    assert [str(a.id) for a in attachments.all()] == [kept["id"]]


# --- who may call, and how often -----------------------------------------------------------


def _routes(task_id: object, attachment_id: object) -> list[tuple[str, str]]:
    return [
        ("POST", f"/tasks/{task_id}/attachments/links"),
        ("POST", f"/tasks/{task_id}/attachments/files"),
        ("GET", f"/tasks/{task_id}/attachments/{attachment_id}/content"),
        ("DELETE", f"/tasks/{task_id}/attachments/{attachment_id}"),
    ]


@pytest.mark.parametrize(("method", "path"), _routes(uuid.uuid4(), uuid.uuid4()))
async def test_every_attachment_route_needs_a_signed_in_user(
    anonymous_client: httpx.AsyncClient, method: str, path: str
) -> None:
    response = await anonymous_client.request(method, path, json=LINK)

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}
    assert response.headers["www-authenticate"] == "Bearer"


async def test_any_signed_in_user_may_change_the_attachments_of_any_task(
    tasks_app: FastAPI,
    task_client: httpx.AsyncClient,
    tasks: InMemoryTaskRepository,
    attachments: InMemoryAttachmentRepository,
) -> None:
    somebody_else = uuid.uuid4()
    task = a_task(somebody_else)
    await tasks.add(task)
    theirs = a_link(task.id, somebody_else)
    await attachments.add(theirs)

    attached = await attach_link(task_client, str(task.id))
    removed = await task_client.delete(f"/tasks/{task.id}/attachments/{theirs.id}")

    assert attached["created_by"] == str(USER_ID)
    assert removed.status_code == 204


@pytest.fixture
async def limited_client(
    minimal_env: pytest.MonkeyPatch, request_scopes: RecordingRequestScopes
) -> AsyncIterator[httpx.AsyncClient]:
    """One request per window: the second one, whatever it is, is over the limit."""
    minimal_env.setenv("RATE_LIMIT__ANONYMOUS__LIMIT", "1")
    container = build_container(load_settings())
    app = create_app(
        container=replace(
            container,
            health_checks=ALL_HEALTHY,
            request_scope=request_scopes,
            rate_limiting=replace(container.rate_limiting, limiter=InMemoryRateLimiter()),
        )
    )
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        yield client


@pytest.mark.parametrize(("method", "path"), _routes(uuid.uuid4(), uuid.uuid4()))
async def test_every_attachment_route_is_rate_limited(
    limited_client: httpx.AsyncClient, method: str, path: str
) -> None:
    assert (await limited_client.get("/tasks")).status_code == 200

    response = await limited_client.request(method, path, json=LINK)

    assert response.status_code == 429
    assert response.json() == {"detail": "Too many requests"}
    assert int(response.headers["retry-after"]) > 0
    assert response.headers["x-ratelimit-remaining"] == "0"


# --- OpenAPI ------------------------------------------------------------------------------------


def _documented(paths: dict[str, Any], path: str, method: str) -> dict[str, str | None]:
    responses = paths[path][method]["responses"]
    found: dict[str, str | None] = {}
    for code, response in responses.items():
        schema = response.get("content", {}).get("application/json", {}).get("schema", {})
        found[code] = schema.get("$ref", "").rpartition("/")[2] or None
    return found


async def test_openapi_documents_every_link_and_removal_response(
    task_client: httpx.AsyncClient,
) -> None:
    schema = (await task_client.get("/openapi.json")).json()
    paths, components = schema["paths"], schema["components"]["schemas"]
    error, invalid = "ErrorResponse", "HTTPValidationError"

    assert _documented(paths, "/tasks/{id_or_key}/attachments/links", "post") == {
        "201": "AttachmentResponse",
        "401": error,
        "404": error,
        "422": invalid,
        "429": error,
    }
    assert _documented(paths, "/tasks/{id_or_key}/attachments/{attachment_id}", "delete") == {
        "204": None,
        "401": error,
        "404": error,
        "422": invalid,
        "429": error,
    }
    assert _documented(paths, "/tasks/{id_or_key}", "get")["200"] == "TaskDetailResponse"
    assert components["AttachmentKind"]["enum"] == ["link", "pdf", "image"]
    assert components["LinkCreate"]["required"] == ["url"]
    assert components["LinkCreate"]["properties"]["url"]["maxLength"] == 2000
    assert "storage_key" not in components["AttachmentResponse"]["properties"]
    assert "attachments_count" in components["TaskResponse"]["required"]
    assert {"attachments", "attachments_count"} <= set(components["TaskDetailResponse"]["required"])
