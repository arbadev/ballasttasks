"""Register, log in and read /auth/me through the real adapters: PostgreSQL, Argon2, JWT."""

import asyncio
from collections.abc import AsyncIterator

import httpx
import jwt
import pytest

from app.bootstrap import build_container, load_settings
from app.main import create_app

pytestmark = pytest.mark.integration

ADA = {"email": "ada@example.com", "full_name": "Ada Lovelace", "password": "correct horse"}


@pytest.fixture
async def client(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    app = create_app(container=build_container(load_settings()))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http,
    ):
        yield http


async def test_register_login_and_me_against_the_real_stack(client: httpx.AsyncClient) -> None:
    registered = await client.post("/auth/register", json=ADA)
    assert registered.status_code == 201

    duplicate = await client.post("/auth/register", json={**ADA, "email": "ADA@example.com"})
    assert duplicate.status_code == 409

    login = await client.post(
        "/auth/login", data={"username": ADA["email"], "password": ADA["password"]}
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    settings = load_settings()
    claims = jwt.decode(
        token,
        settings.auth.jwt_secret.get_secret_value(),
        algorithms=[settings.auth.jwt_algorithm],
    )
    assert claims["sub"] == registered.json()["id"]

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json() == registered.json()

    wrong = await client.post(
        "/auth/login", data={"username": ADA["email"], "password": "not the password"}
    )
    assert wrong.status_code == 401


async def test_concurrent_registrations_of_one_email_yield_one_201_and_the_rest_409(
    client: httpx.AsyncClient,
) -> None:
    payload = {**ADA, "email": "race@example.com"}

    responses = await asyncio.gather(
        *(client.post("/auth/register", json=payload) for _ in range(6))
    )

    assert sorted(response.status_code for response in responses) == [201, 409, 409, 409, 409, 409]
