"""The task routes as a client meets them: register, log in, then use the bearer token.

Nothing is faked or overridden: HTTP -> ``get_current_user_id`` -> use case -> SQLAlchemy ->
PostgreSQL, with Argon2 hashes and real JWTs.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
import sqlalchemy
from fastapi import FastAPI

from app.bootstrap import Container, RequestScope, build_container, load_settings
from app.infrastructure.db.unit_of_work import transactional_session
from app.main import create_app

pytestmark = pytest.mark.integration

# ``GET /tasks/{id_or_key}`` is the detail: the task as every other route shows it, plus what
# is attached to it.
NOTHING_ATTACHED: dict[str, object] = {"attachments": []}

PASSWORD = "correct horse battery"
INVALID_ASSIGNEE = {
    "detail": [
        {
            "type": "invalid_assignee",
            "loc": ["body", "assignee_id"],
            "msg": "assignee_id must be the id of an active user",
        }
    ]
}


@asynccontextmanager
async def http_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http,
    ):
        yield http


@pytest.fixture
def container(migrated_database_url: str, monkeypatch: pytest.MonkeyPatch) -> Container:
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    return build_container(load_settings())


@pytest.fixture
async def client(container: Container) -> AsyncIterator[httpx.AsyncClient]:
    async with http_client(create_app(container=container)) as http:
        yield http


@dataclass(frozen=True, slots=True)
class SignedIn:
    id: str
    headers: dict[str, str]


async def register_and_log_in(client: httpx.AsyncClient, full_name: str) -> SignedIn:
    email = f"{uuid.uuid4().hex}@example.com"
    registered = await client.post(
        "/auth/register", json={"email": email, "full_name": full_name, "password": PASSWORD}
    )
    assert registered.status_code == 201, registered.text
    login = await client.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return SignedIn(
        id=registered.json()["id"],
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )


async def deactivate(container: Container, user_id: str) -> None:
    """There is no endpoint for it (yet); an operator would do exactly this."""
    async with transactional_session(container.session_factory) as session:
        await session.execute(
            sqlalchemy.text("UPDATE users SET is_active = false WHERE id = :id"),
            {"id": uuid.UUID(user_id)},
        )


async def test_a_task_lives_through_create_list_get_assign_complete_and_delete(
    client: httpx.AsyncClient,
) -> None:
    ada = await register_and_log_in(client, "Ada Lovelace")
    grace = await register_and_log_in(client, "Grace Hopper")

    created = await client.post(
        "/tasks", json={"title": "Write the report", "due_date": "2026-10-01"}, headers=ada.headers
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["created_by"] == ada.id
    assert task["assignee_id"] is None
    assert task["status"] == "todo"

    # Each request is its own transaction: what one committed, the next one reads.
    listed = await client.get("/tasks", headers=ada.headers)
    assert listed.status_code == 200
    assert task in listed.json()["items"]
    fetched = await client.get(f"/tasks/{task['id']}", headers=ada.headers)
    assert fetched.status_code == 200
    assert fetched.json() == task | NOTHING_ATTACHED

    assigned = await client.patch(
        f"/tasks/{task['id']}", json={"assignee_id": grace.id}, headers=ada.headers
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["assignee_id"] == grace.id

    # Any authenticated user may change any task: the assignee completes it herself.
    done = await client.patch(
        f"/tasks/{task['id']}", json={"status": "done"}, headers=grace.headers
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "done"
    assert done.json()["completed_at"] is not None
    assert done.json()["assignee_id"] == grace.id
    assert done.json()["created_by"] == ada.id
    assert (
        await client.get(f"/tasks/{task['id']}", headers=ada.headers)
    ).json() == done.json() | NOTHING_ATTACHED

    deleted = await client.delete(f"/tasks/{task['id']}", headers=ada.headers)
    assert deleted.status_code == 204
    assert (await client.get(f"/tasks/{task['id']}", headers=ada.headers)).status_code == 404


async def test_a_task_can_be_created_already_assigned(client: httpx.AsyncClient) -> None:
    ada = await register_and_log_in(client, "Ada Lovelace")
    grace = await register_and_log_in(client, "Grace Hopper")

    created = await client.post(
        "/tasks", json={"title": "Review the report", "assignee_id": grace.id}, headers=ada.headers
    )

    assert created.status_code == 201, created.text
    assert created.json()["assignee_id"] == grace.id


async def test_a_rejected_request_stores_nothing(client: httpx.AsyncClient) -> None:
    ada = await register_and_log_in(client, "Ada Lovelace")
    before = (await client.get("/tasks", headers=ada.headers)).json()

    rejected = await client.post("/tasks", json={"title": "   "}, headers=ada.headers)

    assert rejected.status_code == 422
    assert (await client.get("/tasks", headers=ada.headers)).json() == before


# --- who is calling ------------------------------------------------------------------------


def expired_token_for(user_id: str) -> str:
    """Signed with the real key for a real user: the expiry is the only thing wrong with it."""
    settings = load_settings()
    an_hour_ago = datetime.now(UTC) - timedelta(hours=1)
    return jwt.encode(
        {"sub": user_id, "iat": an_hour_ago - timedelta(minutes=30), "exp": an_hour_ago},
        settings.auth.jwt_secret.get_secret_value(),
        algorithm=settings.auth.jwt_algorithm,
    )


ROUTES = [
    ("POST", "/tasks"),
    ("GET", "/tasks"),
    ("GET", "/tasks/{task_id}"),
    ("PATCH", "/tasks/{task_id}"),
    ("DELETE", "/tasks/{task_id}"),
]


@pytest.mark.parametrize("credentials", ["no token", "garbage token", "expired token"])
@pytest.mark.parametrize(("method", "path"), ROUTES)
async def test_every_task_route_answers_401_without_a_valid_token_and_touches_nothing(
    client: httpx.AsyncClient, method: str, path: str, credentials: str
) -> None:
    ada = await register_and_log_in(client, "Ada Lovelace")
    task = (await client.post("/tasks", json={"title": "Keep me"}, headers=ada.headers)).json()
    headers = {
        "no token": {},
        "garbage token": {"Authorization": "Bearer not.a.jwt"},
        "expired token": {"Authorization": f"Bearer {expired_token_for(ada.id)}"},
    }[credentials]

    response = await client.request(
        method, path.format(task_id=task["id"]), json={"title": "Hijacked"}, headers=headers
    )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert set(response.json()) == {"detail"}
    assert (
        await client.get(f"/tasks/{task['id']}", headers=ada.headers)
    ).json() == task | NOTHING_ATTACHED


async def test_a_deactivated_user_is_locked_out_of_the_task_routes_at_once(
    client: httpx.AsyncClient, container: Container
) -> None:
    ada = await register_and_log_in(client, "Ada Lovelace")
    assert (await client.get("/tasks", headers=ada.headers)).status_code == 200

    await deactivate(container, ada.id)

    assert (await client.get("/tasks", headers=ada.headers)).status_code == 401


# --- who can be given a task ---------------------------------------------------------------


@pytest.mark.parametrize("assignee", ["unknown", "inactive"])
async def test_create_answers_422_when_the_assignee_is_not_an_active_user(
    client: httpx.AsyncClient, container: Container, assignee: str
) -> None:
    ada = await register_and_log_in(client, "Ada Lovelace")
    assignee_id = str(uuid.uuid4())
    if assignee == "inactive":
        assignee_id = (await register_and_log_in(client, "Left The Team")).id
        await deactivate(container, assignee_id)
    before = (await client.get("/tasks", headers=ada.headers)).json()

    response = await client.post(
        "/tasks",
        json={"title": "Write the report", "assignee_id": assignee_id},
        headers=ada.headers,
    )

    assert response.status_code == 422
    assert response.json() == INVALID_ASSIGNEE
    assert (await client.get("/tasks", headers=ada.headers)).json() == before


@pytest.mark.parametrize("assignee", ["unknown", "inactive"])
async def test_patch_answers_422_when_the_assignee_is_not_an_active_user(
    client: httpx.AsyncClient, container: Container, assignee: str
) -> None:
    ada = await register_and_log_in(client, "Ada Lovelace")
    assignee_id = str(uuid.uuid4())
    if assignee == "inactive":
        assignee_id = (await register_and_log_in(client, "Left The Team")).id
        await deactivate(container, assignee_id)
    task = (await client.post("/tasks", json={"title": "Keep me"}, headers=ada.headers)).json()

    response = await client.patch(
        f"/tasks/{task['id']}",
        json={"title": "Changed", "assignee_id": assignee_id},
        headers=ada.headers,
    )

    assert response.status_code == 422
    assert response.json() == INVALID_ASSIGNEE
    assert (
        await client.get(f"/tasks/{task['id']}", headers=ada.headers)
    ).json() == task | NOTHING_ATTACHED


async def test_a_task_outlives_the_deactivation_of_its_assignee(
    client: httpx.AsyncClient, container: Container
) -> None:
    ada = await register_and_log_in(client, "Ada Lovelace")
    grace = await register_and_log_in(client, "Grace Hopper")
    task = (
        await client.post(
            "/tasks",
            json={"title": "Write the report", "assignee_id": grace.id},
            headers=ada.headers,
        )
    ).json()
    await deactivate(container, grace.id)

    done = await client.patch(f"/tasks/{task['id']}", json={"status": "done"}, headers=ada.headers)

    assert done.status_code == 200, done.text
    assert done.json()["assignee_id"] == grace.id


async def test_patch_may_name_the_deactivated_assignee_the_task_already_has(
    client: httpx.AsyncClient, container: Container
) -> None:
    """A form that saves the whole task names the assignee without changing it; changing it
    to somebody who is not active is still refused."""
    ada = await register_and_log_in(client, "Ada Lovelace")
    grace = await register_and_log_in(client, "Grace Hopper")
    left_too = await register_and_log_in(client, "Left The Team")
    task = (
        await client.post(
            "/tasks",
            json={"title": "Write the report", "assignee_id": grace.id},
            headers=ada.headers,
        )
    ).json()
    await deactivate(container, grace.id)
    await deactivate(container, left_too.id)

    saved = await client.patch(
        f"/tasks/{task['id']}",
        json={"title": "Publish the report", "assignee_id": grace.id},
        headers=ada.headers,
    )
    changed = await client.patch(
        f"/tasks/{task['id']}",
        json={"title": "Changed", "assignee_id": left_too.id},
        headers=ada.headers,
    )

    assert saved.status_code == 200, saved.text
    assert saved.json()["title"] == "Publish the report"
    assert saved.json()["assignee_id"] == grace.id
    assert changed.status_code == 422
    assert changed.json() == INVALID_ASSIGNEE
    assert (
        await client.get(f"/tasks/{task['id']}", headers=ada.headers)
    ).json() == saved.json() | NOTHING_ATTACHED


async def test_the_foreign_key_answers_the_same_422_when_the_check_is_outrun(
    container: Container,
) -> None:
    """The race-safe backstop, end to end: a directory that says yes to everybody stands in
    for a user who vanished after the check, so only ``fk_tasks_assignee_id_users`` is left
    to refuse the task. The answer is the client error, never a 500."""

    class EverybodyIsActive:
        async def is_active_user(self, user_id: uuid.UUID) -> bool:
            return True

    @asynccontextmanager
    async def request_scope() -> AsyncIterator[RequestScope]:
        async with container.request_scope() as scope:
            yield replace(scope, user_directory=EverybodyIsActive())

    app = create_app(container=replace(container, request_scope=request_scope))
    async with http_client(app) as client:
        ada = await register_and_log_in(client, "Ada Lovelace")
        task = (await client.post("/tasks", json={"title": "Keep me"}, headers=ada.headers)).json()
        nobody = str(uuid.uuid4())

        created = await client.post(
            "/tasks", json={"title": "t", "assignee_id": nobody}, headers=ada.headers
        )
        patched = await client.patch(
            f"/tasks/{task['id']}", json={"assignee_id": nobody}, headers=ada.headers
        )

        assert (created.status_code, created.json()) == (422, INVALID_ASSIGNEE)
        assert (patched.status_code, patched.json()) == (422, INVALID_ASSIGNEE)
        assert (
            await client.get(f"/tasks/{task['id']}", headers=ada.headers)
        ).json() == task | NOTHING_ATTACHED
