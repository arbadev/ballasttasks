"""Browser persistence is a verified cookie, never a client-side logged-in flag."""

from dataclasses import replace

import httpx
import pytest

from tests.api.conftest import AuthFakes
from tests.api.test_sso import sign_in as sso_code

ORIGIN = "http://localhost:3000"
BROWSER = {"Origin": ORIGIN, "X-CSRF-Protection": "1"}
FORM = {"username": "browser@example.test", "password": "synthetic-password"}


async def test_anonymous_bootstrap_is_a_normal_empty_session(
    auth_client: httpx.AsyncClient,
) -> None:
    response = await auth_client.get("/auth/session")
    assert response.status_code == 200
    assert response.json() is None
    assert response.headers["cache-control"] == "no-store"


async def register(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/auth/register",
        json={"email": FORM["username"], "full_name": "Browser", "password": FORM["password"]},
    )
    assert response.status_code == 201


async def test_browser_session_survives_new_client_and_logout(
    auth_client: httpx.AsyncClient,
) -> None:
    await register(auth_client)
    login = await auth_client.post("/auth/session", data=FORM, headers=BROWSER)
    assert login.status_code == 200
    assert "access_token" not in login.json()
    cookie = login.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "Max-Age=1800" in cookie
    assert login.headers["cache-control"] == "no-store"
    # The new client has no bearer header or remembered user; only the browser cookie jar.
    async with httpx.AsyncClient(
        transport=auth_client._transport, base_url="http://test", cookies=auth_client.cookies
    ) as tab:
        restored = await tab.get("/auth/session")
        assert restored.status_code == 200
        assert restored.json()["email"] == FORM["username"]
        assert (await tab.get("/tasks")).status_code == 200
        assert (await tab.delete("/auth/session", headers=BROWSER)).status_code == 204
        anonymous = await tab.get("/auth/session")
        assert anonymous.status_code == 200
        assert anonymous.json() is None
        assert (await tab.get("/tasks")).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": ORIGIN},
        {"X-CSRF-Protection": "1"},
        {"Origin": "https://evil.test", "X-CSRF-Protection": "1"},
        {"Origin": "null", "X-CSRF-Protection": "1"},
    ],
)
async def test_cookie_login_requires_origin_and_non_simple_header(
    auth_client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    await register(auth_client)
    response = await auth_client.post("/auth/session", data=FORM, headers=headers)
    assert response.status_code == 403
    assert "set-cookie" not in response.headers


async def test_cookie_writes_require_csrf_but_bearer_still_works(
    auth_client: httpx.AsyncClient,
) -> None:
    await register(auth_client)
    assert (await auth_client.post("/auth/session", data=FORM, headers=BROWSER)).status_code == 200
    for headers in (
        {},
        {"Origin": ORIGIN},
        {"Origin": "http://localhost:3001", "X-CSRF-Protection": "1"},
    ):
        assert (
            await auth_client.post("/tasks", json={"title": "refused"}, headers=headers)
        ).status_code == 403
        assert (
            await auth_client.post("/tasks/missing/attachments/files", headers=headers)
        ).status_code == 403
    assert (
        await auth_client.post("/tasks", json={"title": "allowed"}, headers=BROWSER)
    ).status_code == 201
    bearer = (await auth_client.post("/auth/login", data=FORM)).json()["access_token"]
    assert (
        await auth_client.post(
            "/tasks", json={"title": "bearer"}, headers={"Authorization": f"Bearer {bearer}"}
        )
    ).status_code == 201
    # An explicitly invalid bearer never falls back to a valid cookie.
    assert (
        await auth_client.get("/tasks", headers={"Authorization": "Bearer invalid"})
    ).status_code == 401


async def test_cookie_resolves_active_user_each_time(
    auth_client: httpx.AsyncClient, auth_fakes: AuthFakes
) -> None:
    await register(auth_client)
    assert (await auth_client.post("/auth/session", data=FORM, headers=BROWSER)).status_code == 200
    user = await auth_fakes.users.get_by_email(FORM["username"])
    assert user is not None
    await auth_fakes.users.update(replace(user, is_active=False))
    assert (await auth_client.get("/auth/session")).status_code == 401
    assert (await auth_client.get("/tasks")).status_code == 401


async def test_cookie_sso_exchange_is_single_use_and_never_returns_jwt(
    auth_client: httpx.AsyncClient,
) -> None:
    code = await sso_code(auth_client)
    response = await auth_client.post("/auth/session/sso", json={"code": code}, headers=BROWSER)
    assert response.status_code == 200
    assert "access_token" not in response.json()
    assert "HttpOnly" in response.headers["set-cookie"]
    assert (await auth_client.get("/tasks")).status_code == 200
    assert (
        await auth_client.post("/auth/session/sso", json={"code": code}, headers=BROWSER)
    ).status_code == 401


async def test_credentialed_cors_is_exact_and_allows_only_known_headers(
    auth_client: httpx.AsyncClient,
) -> None:
    preflight = {
        "Origin": ORIGIN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "X-CSRF-Protection,Content-Type",
    }
    response = await auth_client.options("/auth/session", headers=preflight)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    bad = await auth_client.options(
        "/auth/session", headers={**preflight, "Origin": "https://evil.test"}
    )
    assert bad.status_code == 400
    assert "access-control-allow-origin" not in bad.headers
