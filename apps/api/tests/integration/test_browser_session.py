"""Real PostgreSQL/Argon2/JWT cookie restoration and expiry, normal rate-limit policy."""

from collections.abc import AsyncIterator
from datetime import timedelta

import httpx
import jwt
import pytest

from app.application.clock import utc_now
from app.bootstrap import build_container, load_settings
from app.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def rate_limit_keys_of_its_own() -> None:
    """This acceptance test deliberately keeps the configured prefix and normal budgets.

    It uses only two credential attempts. Run against an owned stack in a naturally
    available auth window, never by resetting counters or changing their namespace.
    """


@pytest.fixture
async def browser(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    app = create_app(container=build_container(load_settings()))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


async def test_real_cookie_restore_expiry_invalidation_and_bearer(
    browser: httpx.AsyncClient,
) -> None:
    settings = load_settings()
    origin = settings.cors.allowed_origins[0]
    csrf = {"Origin": origin, "X-CSRF-Protection": "1"}
    body = {
        "email": "cookie-real@example.test",
        "full_name": "Cookie Real",
        "password": "synthetic-session-password",
    }
    registered = await browser.post("/auth/register", json=body)
    assert registered.status_code == 201
    signed = await browser.post(
        "/auth/session",
        headers=csrf,
        data={"username": body["email"], "password": body["password"]},
    )
    assert signed.status_code == 200
    opaque = browser.cookies.get("bt_session")
    assert opaque is not None
    claims = jwt.decode(
        opaque,
        settings.auth.jwt_secret.get_secret_value(),
        algorithms=[settings.auth.jwt_algorithm],
    )
    assert claims["exp"] - claims["iat"] == settings.auth.access_token_expire_minutes * 60
    restored = await browser.get("/auth/session")
    assert restored.json()["id"] == registered.json()["id"]
    assert "set-cookie" not in restored.headers  # no silent lifetime extension
    assert (
        await browser.post("/tasks", json={"title": "Persisted cookie task"}, headers=csrf)
    ).status_code == 201
    assert (await browser.get("/tasks")).json()["total"] == 1
    # Same signed JWT works for independent bearer clients, without cookie CSRF requirements.
    assert (
        await browser.post(
            "/tasks", json={"title": "Bearer task"}, headers={"Authorization": f"Bearer {opaque}"}
        )
    ).status_code == 201
    past = utc_now() - timedelta(minutes=60)
    expired = jwt.encode(
        {"sub": claims["sub"], "iat": past, "exp": past + timedelta(minutes=1)},
        settings.auth.jwt_secret.get_secret_value(),
        algorithm=settings.auth.jwt_algorithm,
    )
    browser.cookies.clear()
    browser.cookies.set("bt_session", expired)
    assert (await browser.get("/auth/session")).status_code == 401
    assert (await browser.get("/tasks")).status_code == 401
    browser.cookies.clear()
    browser.cookies.set("bt_session", "invalid-session")
    assert (await browser.get("/auth/session")).status_code == 401
    browser.cookies.clear()
    assert (await browser.delete("/auth/session", headers=csrf)).status_code == 204
    assert (await browser.get("/auth/session")).json() is None
