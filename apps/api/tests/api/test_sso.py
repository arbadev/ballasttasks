"""The single sign-on routes, around a container of fakes: no database, no Redis, no Google.

start -> (provider) -> callback -> web app -> exchange. Redirect targets are the ones in
settings, whatever the request says; every failure of the callback is one constant redirect,
and every failure of the exchange is one constant ``401``.
"""

import dataclasses
import logging
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI

from app.application.errors import (
    IdentityCodeRejectedError,
    IdentityProviderUnavailableError,
)
from app.application.sso import EXCHANGE_CODE_TTL, STATE_TTL, SsoConfig
from tests.api.conftest import AuthFakes, SsoFakes
from tests.auth_fakes import a_user
from tests.sso_fakes import StubIdentityProvider, an_identity

API = "http://localhost:8000"
WEB_CALLBACK = "http://localhost:3000/auth/callback"
SSO_FAILED = f"{WEB_CALLBACK}?error=sso_failed"
PROVIDER_UNAVAILABLE = f"{WEB_CALLBACK}?error=provider_unavailable"
UNKNOWN_PROVIDER = {"detail": "Unknown single sign-on provider"}
INVALID_CODE = {"detail": "Invalid or expired code"}
DEMO_EMAIL = "demo.sso@example.com"


def path_and_query(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}"


def query_of(url: str) -> dict[str, str]:
    return {name: values[0] for name, values in parse_qs(urlsplit(url).query).items()}


async def start(client: httpx.AsyncClient, provider: str = "fake") -> str:
    """Begin a sign-in; returns where the provider sends the browser back to."""
    response = await client.get(f"/auth/sso/{provider}/start")
    assert response.status_code == 303
    return response.headers["location"]


async def sign_in(client: httpx.AsyncClient, provider: str = "fake") -> str:
    """The whole browser part; returns the one-time exchange code the web app receives."""
    callback = await client.get(path_and_query(await start(client, provider)))
    assert callback.status_code == 303
    location = callback.headers["location"]
    assert location.startswith(f"{WEB_CALLBACK}?code=")
    return query_of(location)["code"]


# --- providers -------------------------------------------------------------------------


async def test_the_login_screen_can_list_the_enabled_providers(
    auth_client: httpx.AsyncClient,
) -> None:
    response = await auth_client.get("/auth/sso/providers")

    assert response.status_code == 200
    assert response.json() == {"providers": [{"name": "fake"}]}


async def test_no_provider_is_listed_while_single_sign_on_is_disabled(
    auth_client: httpx.AsyncClient, sso_fakes: SsoFakes
) -> None:
    sso_fakes.providers.clear()

    response = await auth_client.get("/auth/sso/providers")

    assert response.status_code == 200
    assert response.json() == {"providers": []}


# --- start -----------------------------------------------------------------------------


async def test_start_redirects_to_the_provider_with_a_state_and_binds_the_browser(
    auth_client: httpx.AsyncClient,
) -> None:
    response = await auth_client.get("/auth/sso/fake/start")

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith(f"{API}/auth/sso/fake/callback?")
    assert len(query_of(location)["state"]) >= 32
    assert response.headers["cache-control"] == "no-store"

    cookie = response.headers["set-cookie"]
    name_value, *attributes = [part.strip() for part in cookie.split(";")]
    assert name_value.startswith("sso_binding=")
    assert len(name_value.removeprefix("sso_binding=")) >= 32
    assert {attribute.lower() for attribute in attributes} == {
        "httponly",
        "samesite=lax",
        "path=/auth/sso",
        f"max-age={int(STATE_TTL.total_seconds())}",
    }


async def test_the_binding_cookie_is_secure_when_the_api_is_served_over_https(
    auth_app: FastAPI, auth_client: httpx.AsyncClient
) -> None:
    auth_app.state.container = replace(
        auth_app.state.container,
        sso=SsoConfig(api_public_base_url="https://api.example", web_callback_url=WEB_CALLBACK),
    )

    response = await auth_client.get("/auth/sso/fake/start")

    assert response.headers["location"].startswith("https://api.example/auth/sso/fake/callback?")
    assert "secure" in {part.strip().lower() for part in response.headers["set-cookie"].split(";")}


async def test_the_state_is_not_the_cookie_value(auth_client: httpx.AsyncClient) -> None:
    """Whoever sees the URL (history, a proxy log) must not learn the browser binding."""
    response = await auth_client.get("/auth/sso/fake/start")

    binding = response.cookies["sso_binding"]
    assert binding not in response.headers["location"]


@pytest.mark.parametrize("provider", ["google", "myspace", "FAKE", "fake%20"])
async def test_an_unknown_and_a_disabled_provider_are_the_same_404(
    auth_client: httpx.AsyncClient, provider: str
) -> None:
    """``google`` is registered but not enabled here; ``myspace`` does not exist."""
    started = await auth_client.get(f"/auth/sso/{provider}/start")
    called_back = await auth_client.get(f"/auth/sso/{provider}/callback?code=c&state=s")

    for response in (started, called_back):
        assert response.status_code == 404
        assert response.json() == UNKNOWN_PROVIDER
        assert "set-cookie" not in response.headers


async def test_start_with_an_unreachable_provider_sends_the_browser_back_to_the_web_app(
    auth_client: httpx.AsyncClient, sso_fakes: SsoFakes
) -> None:
    class Unreachable(StubIdentityProvider):
        async def authorization_url(self, *, state: str, nonce: str, redirect_uri: str) -> str:
            raise IdentityProviderUnavailableError

    sso_fakes.providers["stub"] = Unreachable("stub", IdentityProviderUnavailableError())

    response = await auth_client.get("/auth/sso/stub/start")

    assert response.status_code == 303
    assert response.headers["location"] == PROVIDER_UNAVAILABLE
    assert "set-cookie" not in response.headers
    assert sso_fakes.store.stored_keys() == []


EVIL = "https://evil.example/steal"


@pytest.mark.parametrize(
    "parameter", ["redirect_uri", "redirect", "next", "return_to", "callback", "url"]
)
async def test_no_request_parameter_or_header_can_choose_a_redirect_target(
    auth_client: httpx.AsyncClient, parameter: str
) -> None:
    headers = {"Host": "evil.example", "X-Forwarded-Host": "evil.example", "Referer": EVIL}

    started = await auth_client.get(
        "/auth/sso/fake/start", params={parameter: EVIL}, headers=headers
    )
    assert started.headers["location"].startswith(f"{API}/auth/sso/fake/callback?")

    callback_url = path_and_query(started.headers["location"]) + f"&{parameter}={EVIL}"
    finished = await auth_client.get(callback_url, headers=headers)
    failed = await auth_client.get(callback_url, headers=headers)

    assert finished.headers["location"].startswith(f"{WEB_CALLBACK}?code=")
    assert failed.headers["location"] == SSO_FAILED
    for response in (started, finished, failed):
        assert "evil.example" not in response.headers["location"]


# --- callback --------------------------------------------------------------------------


async def test_the_callback_hands_the_web_app_a_one_time_code_and_never_the_token(
    auth_client: httpx.AsyncClient, auth_fakes: AuthFakes
) -> None:
    callback = await auth_client.get(path_and_query(await start(auth_client)))

    assert callback.status_code == 303
    location = callback.headers["location"]
    assert set(query_of(location)) == {"code"}
    assert callback.headers["cache-control"] == "no-store"
    assert callback.headers["referrer-policy"] == "no-referrer"
    assert 'sso_binding=""' in callback.headers["set-cookie"]  # the binding is spent too
    assert "max-age=0" in callback.headers["set-cookie"].lower()

    exchanged = await auth_client.post("/auth/sso/exchange", json=query_of(location))
    token = exchanged.json()["access_token"]
    assert token not in location
    assert auth_fakes.tokens.decode(token)


async def test_the_exchange_answers_the_same_body_as_a_password_login(
    auth_client: httpx.AsyncClient,
) -> None:
    exchanged = await auth_client.post(
        "/auth/sso/exchange", json={"code": await sign_in(auth_client)}
    )

    assert exchanged.status_code == 200
    assert set(exchanged.json()) == {"access_token", "token_type"}
    assert exchanged.json()["token_type"] == "bearer"
    assert exchanged.headers["cache-control"] == "no-store"

    me = await auth_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {exchanged.json()['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == DEMO_EMAIL
    assert "hashed_password" not in me.json()


async def test_signing_in_twice_is_one_user(
    auth_client: httpx.AsyncClient, auth_fakes: AuthFakes
) -> None:
    tokens = [
        (
            await auth_client.post("/auth/sso/exchange", json={"code": await sign_in(auth_client)})
        ).json()["access_token"]
        for _ in range(2)
    ]

    assert auth_fakes.tokens.decode(tokens[0]) == auth_fakes.tokens.decode(tokens[1])


async def test_a_verified_email_signs_in_as_the_user_who_registered_with_a_password(
    auth_client: httpx.AsyncClient,
) -> None:
    registered = await auth_client.post(
        "/auth/register",
        json={"email": DEMO_EMAIL, "full_name": "Demo", "password": "correct horse"},
    )

    exchanged = await auth_client.post(
        "/auth/sso/exchange", json={"code": await sign_in(auth_client)}
    )
    me = await auth_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {exchanged.json()['access_token']}"}
    )
    login = await auth_client.post(
        "/auth/login", data={"username": DEMO_EMAIL, "password": "correct horse"}
    )

    assert me.json()["id"] == registered.json()["id"]
    assert login.status_code == 200  # the password still works


async def test_a_user_created_by_single_sign_on_cannot_log_in_with_a_password(
    auth_client: httpx.AsyncClient,
) -> None:
    await sign_in(auth_client)

    for password in ("", "None", "null", "!"):
        login = await auth_client.post(
            "/auth/login", data={"username": DEMO_EMAIL, "password": password}
        )
        assert login.status_code in {401, 422}
        assert "access_token" not in login.text


async def test_a_tampered_state_fails(auth_client: httpx.AsyncClient) -> None:
    sent_back = query_of(await start(auth_client))

    response = await auth_client.get(
        "/auth/sso/fake/callback",
        params={"code": sent_back["code"], "state": sent_back["state"][:-1] + "A"},
    )

    assert response.status_code == 303
    assert response.headers["location"] == SSO_FAILED


async def test_a_replayed_state_fails(auth_client: httpx.AsyncClient) -> None:
    callback_url = path_and_query(await start(auth_client))
    first = await auth_client.get(callback_url)
    binding = first.request.headers["cookie"]

    replayed = await auth_client.get(callback_url, headers={"Cookie": binding})

    assert first.headers["location"].startswith(f"{WEB_CALLBACK}?code=")
    assert replayed.headers["location"] == SSO_FAILED


async def test_an_expired_state_fails(auth_client: httpx.AsyncClient, sso_fakes: SsoFakes) -> None:
    callback_url = path_and_query(await start(auth_client))
    sso_fakes.clock.advance(STATE_TTL)

    response = await auth_client.get(callback_url)

    assert response.headers["location"] == SSO_FAILED


@pytest.mark.parametrize("cookie", [None, "sso_binding=", "sso_binding=another-browser"])
async def test_a_callback_in_a_browser_that_did_not_start_the_flow_fails(
    auth_app: FastAPI, auth_client: httpx.AsyncClient, cookie: str | None
) -> None:
    """Login CSRF: the attacker's state and code, planted in the victim's browser."""
    callback_url = path_and_query(await start(auth_client))

    transport = httpx.ASGITransport(app=auth_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as victim:
        response = await victim.get(callback_url, headers={"Cookie": cookie} if cookie else {})

    assert response.status_code == 303
    assert response.headers["location"] == SSO_FAILED


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"state": "only-a-state"},
        {"code": "only-a-code"},
        {"error": "access_denied"},
        {"error": "access_denied", "state": "{state}"},
        {"error": "access_denied", "state": "{state}", "code": "{code}"},
    ],
)
async def test_a_callback_that_is_not_an_approval_fails(
    auth_client: httpx.AsyncClient, params: dict[str, str]
) -> None:
    """The person declined at the provider, or the URL was cut short."""
    sent_back = query_of(await start(auth_client))
    filled = {name: value.format(**sent_back) for name, value in params.items()}

    response = await auth_client.get("/auth/sso/fake/callback", params=filled)

    assert response.status_code == 303
    assert response.headers["location"] == SSO_FAILED


async def test_a_code_the_provider_rejects_fails(
    auth_client: httpx.AsyncClient, sso_fakes: SsoFakes
) -> None:
    sent_back = query_of(await start(auth_client))

    response = await auth_client.get(
        "/auth/sso/fake/callback", params={**sent_back, "code": "not-the-code"}
    )

    assert response.headers["location"] == SSO_FAILED


@pytest.mark.parametrize(
    ("outcome", "location"),
    [
        (IdentityCodeRejectedError(), SSO_FAILED),
        (an_identity(provider="stub", email_verified=False), SSO_FAILED),
        (an_identity(provider="another-provider"), SSO_FAILED),
        (IdentityProviderUnavailableError(), PROVIDER_UNAVAILABLE),
    ],
    ids=["rejected code", "unverified email", "identity of another provider", "unreachable"],
)
async def test_a_sign_in_the_provider_does_not_vouch_for_fails(
    auth_client: httpx.AsyncClient,
    sso_fakes: SsoFakes,
    auth_fakes: AuthFakes,
    outcome: Exception,
    location: str,
) -> None:
    sso_fakes.providers["stub"] = StubIdentityProvider("stub", outcome)
    state = query_of(await start(auth_client, "stub"))["state"]

    response = await auth_client.get(
        "/auth/sso/stub/callback", params={"code": "c", "state": state}
    )

    assert response.status_code == 303
    assert response.headers["location"] == location
    assert sso_fakes.store.stored_keys() == []  # no exchange code was issued
    assert auth_fakes.users._users == {}  # and nobody was created


async def test_an_inactive_user_cannot_sign_in(
    auth_client: httpx.AsyncClient, auth_fakes: AuthFakes, sso_fakes: SsoFakes
) -> None:
    await auth_fakes.users.add(dataclasses.replace(a_user(is_active=False), email=DEMO_EMAIL))

    response = await auth_client.get(path_and_query(await start(auth_client)))

    assert response.headers["location"] == SSO_FAILED
    assert sso_fakes.store.stored_keys() == []


async def test_a_state_started_at_one_provider_fails_at_another(
    auth_client: httpx.AsyncClient, sso_fakes: SsoFakes
) -> None:
    sso_fakes.providers["stub"] = StubIdentityProvider("stub", an_identity(provider="stub"))
    sent_back = query_of(await start(auth_client, "fake"))

    response = await auth_client.get("/auth/sso/stub/callback", params=sent_back)

    assert response.headers["location"] == SSO_FAILED


async def test_every_failed_callback_spends_the_binding_cookie(
    auth_client: httpx.AsyncClient,
) -> None:
    await start(auth_client)

    response = await auth_client.get("/auth/sso/fake/callback", params={"state": "x", "code": "y"})

    assert "max-age=0" in response.headers["set-cookie"].lower()


@pytest.mark.parametrize("name", ["state", "code"])
async def test_an_over_long_callback_parameter_is_a_422_that_does_not_echo_it(
    auth_client: httpx.AsyncClient, name: str
) -> None:
    value = "A" * 5000

    response = await auth_client.get("/auth/sso/fake/callback", params={name: value})

    assert response.status_code == 422
    assert value[:64] not in response.text


# --- exchange --------------------------------------------------------------------------


async def test_a_replayed_exchange_code_fails(auth_client: httpx.AsyncClient) -> None:
    code = await sign_in(auth_client)
    first = await auth_client.post("/auth/sso/exchange", json={"code": code})

    replayed = await auth_client.post("/auth/sso/exchange", json={"code": code})

    assert first.status_code == 200
    assert replayed.status_code == 401
    assert replayed.json() == INVALID_CODE
    assert replayed.headers["www-authenticate"] == "Bearer"


async def test_an_expired_exchange_code_fails(
    auth_client: httpx.AsyncClient, sso_fakes: SsoFakes
) -> None:
    code = await sign_in(auth_client)
    sso_fakes.clock.advance(EXCHANGE_CODE_TTL)

    response = await auth_client.post("/auth/sso/exchange", json={"code": code})

    assert response.status_code == 401
    assert response.json() == INVALID_CODE


async def test_an_unknown_exchange_code_and_a_state_used_as_one_fail_alike(
    auth_client: httpx.AsyncClient,
) -> None:
    state = query_of(await start(auth_client))["state"]

    for code in ("never-issued", state):
        response = await auth_client.post("/auth/sso/exchange", json={"code": code})
        assert response.status_code == 401
        assert response.json() == INVALID_CODE


async def test_a_user_deactivated_before_the_exchange_gets_no_token(
    auth_client: httpx.AsyncClient, auth_fakes: AuthFakes
) -> None:
    code = await sign_in(auth_client)
    (user,) = auth_fakes.users._users.values()
    auth_fakes.users._users[user.id] = dataclasses.replace(user, is_active=False)

    response = await auth_client.post("/auth/sso/exchange", json={"code": code})

    assert response.status_code == 401
    assert response.json() == INVALID_CODE


@pytest.mark.parametrize(
    "body",
    [{}, {"code": ""}, {"code": None}, {"code": "A" * 5000}, {"code": "c", "redirect": "x"}],
)
async def test_a_malformed_exchange_body_is_a_422_that_echoes_nothing(
    auth_client: httpx.AsyncClient, body: dict[str, object]
) -> None:
    response = await auth_client.post("/auth/sso/exchange", json=body)

    assert response.status_code == 422
    assert all("input" not in item for item in response.json()["detail"])
    assert "A" * 64 not in response.text


async def test_the_exchange_code_is_not_accepted_in_the_url(auth_client: httpx.AsyncClient) -> None:
    code = await sign_in(auth_client)

    response = await auth_client.post("/auth/sso/exchange", params={"code": code})

    assert response.status_code == 422


# --- nothing secret is written down ----------------------------------------------------


async def test_no_log_line_carries_a_state_a_code_a_binding_or_a_token(
    auth_client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    secrets: list[str] = []

    started = await auth_client.get("/auth/sso/fake/start")
    sent_back = query_of(started.headers["location"])
    secrets += [sent_back["state"], sent_back["code"], started.cookies["sso_binding"]]
    callback = await auth_client.get(path_and_query(started.headers["location"]))
    exchange_code = query_of(callback.headers["location"])["code"]
    exchanged = await auth_client.post("/auth/sso/exchange", json={"code": exchange_code})
    secrets += [exchange_code, exchanged.json()["access_token"]]
    # and the failure paths, which are the ones tempted to explain themselves
    await auth_client.get(path_and_query(started.headers["location"]))
    await auth_client.post("/auth/sso/exchange", json={"code": exchange_code})

    app_lines = "\n".join(
        record.getMessage() for record in caplog.records if record.name.startswith("app")
    )
    for secret in secrets:
        assert secret not in app_lines
