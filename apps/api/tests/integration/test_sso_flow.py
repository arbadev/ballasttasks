"""Single sign-on end to end over real HTTP: a uvicorn server on a local port, PostgreSQL,
Redis, Argon2 and real JWTs. Only the identity provider is the fake one (no Google
credentials exist here), enabled exactly as an operator would: ``SSO__ENABLED_PROVIDERS``.

The test plays the browser: it follows each redirect by hand with a cookie jar, then plays
the web app: it swaps the one-time code for the access token and uses it.
"""

import asyncio
import socket
import threading
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
import sqlalchemy
import uvicorn

from app.application.ports.identity_provider import VerifiedIdentity
from app.bootstrap import build_container, load_settings
from app.infrastructure.identity.fake import FakeIdentityProvider
from app.infrastructure.identity.registry import IDENTITY_PROVIDERS
from app.main import create_app

pytestmark = pytest.mark.integration

WEB_CALLBACK = "http://web.test:3000/auth/callback"
PASSWORD = "correct horse battery"


@dataclass(frozen=True)
class Person:
    subject: str
    email: str

    @classmethod
    def new(cls) -> Person:
        unique = uuid.uuid4().hex
        return cls(subject=f"subject-{unique}", email=f"{unique}@example.com")

    def identity(self, *, email_verified: bool = True) -> VerifiedIdentity:
        return VerifiedIdentity(
            provider="fake",
            subject=self.subject,
            email=self.email,
            email_verified=email_verified,
            full_name="Ada Lovelace",
        )


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def at_the_provider() -> FakeIdentityProvider:
    """``identity`` is who the provider vouches for next: the stand-in for a Google account."""
    return FakeIdentityProvider(Person.new().identity())


@pytest.fixture
def api_url(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    at_the_provider: FakeIdentityProvider,
) -> Iterator[str]:
    """The real app, built by the real composition root, served by uvicorn on a TCP port."""
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    monkeypatch.setenv("SSO__ENABLED_PROVIDERS", '["fake"]')
    monkeypatch.setenv("SSO__API_PUBLIC_BASE_URL", base_url)
    monkeypatch.setenv("SSO__WEB_CALLBACK_URL", WEB_CALLBACK)
    # Every request here comes from 127.0.0.1, and six tabs sign in at once: that is not what
    # the strict per-IP budget is for. The limiter stays on (tests/api/test_sso_rate_limit.py).
    monkeypatch.setenv("RATE_LIMIT__AUTH__LIMIT", "200")
    monkeypatch.setitem(IDENTITY_PROVIDERS, "fake", lambda settings: at_the_provider)

    app = create_app(container=build_container(load_settings()))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            threading.Event().wait(0.05)
        assert server.started, "uvicorn did not start"
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture
async def browser(api_url: str) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=api_url, follow_redirects=False) as client:
        yield client


@pytest.fixture
async def web_app(api_url: str) -> AsyncIterator[httpx.AsyncClient]:
    """The web app's calls: another origin, so it shares no cookie with the browser's jar."""
    async with httpx.AsyncClient(base_url=api_url) as client:
        yield client


def query_of(url: str) -> dict[str, str]:
    return {name: values[0] for name, values in parse_qs(urlsplit(url).query).items()}


async def sign_in_through_the_browser(browser: httpx.AsyncClient) -> str:
    """start -> provider -> callback; returns where the browser finally lands."""
    started = await browser.get("/auth/sso/fake/start")
    assert started.status_code == 303, started.text
    at_provider = started.headers["location"]
    assert at_provider.startswith(str(browser.base_url))

    called_back = await browser.get(at_provider)
    assert called_back.status_code == 303, called_back.text
    return str(called_back.headers["location"])


async def access_token(browser: httpx.AsyncClient, web_app: httpx.AsyncClient) -> str:
    landed = await sign_in_through_the_browser(browser)
    assert landed.startswith(f"{WEB_CALLBACK}?code="), landed
    exchanged = await web_app.post("/auth/sso/exchange", json={"code": query_of(landed)["code"]})
    assert exchanged.status_code == 200, exchanged.text
    return str(exchanged.json()["access_token"])


def stored(database_url: str, query: str, **params: object) -> list[tuple[object, ...]]:
    engine = sqlalchemy.create_engine(database_url)
    try:
        with engine.connect() as connection:
            return [tuple(row) for row in connection.execute(sqlalchemy.text(query), params)]
    finally:
        engine.dispose()


async def test_a_first_sign_in_creates_the_user_and_the_token_is_the_apps_normal_jwt(
    browser: httpx.AsyncClient,
    web_app: httpx.AsyncClient,
    at_the_provider: FakeIdentityProvider,
    migrated_database_url: str,
) -> None:
    providers = await web_app.get("/auth/sso/providers")
    assert providers.json() == {"providers": [{"name": "fake"}]}

    token = await access_token(browser, web_app)

    settings = load_settings()
    claims = jwt.decode(
        token,
        settings.auth.jwt_secret.get_secret_value(),
        algorithms=[settings.auth.jwt_algorithm],
    )
    assert set(claims) == {"sub", "iat", "exp"}

    headers = {"Authorization": f"Bearer {token}"}
    me = await web_app.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["id"] == claims["sub"]
    assert me.json()["email"] == at_the_provider.identity.email

    # Nothing downstream changes: the token opens the task routes like any other.
    created = await web_app.post("/tasks", json={"title": "Signed in with SSO"}, headers=headers)
    assert created.status_code == 201, created.text
    assert created.json()["created_by"] == claims["sub"]

    assert stored(
        migrated_database_url,
        "SELECT hashed_password FROM users WHERE id = :id",
        id=uuid.UUID(claims["sub"]),
    ) == [(None,)]
    assert stored(
        migrated_database_url,
        "SELECT provider, subject FROM user_identities WHERE user_id = :id",
        id=uuid.UUID(claims["sub"]),
    ) == [("fake", at_the_provider.identity.subject)]

    # No password exists, so no password logs in.
    login = await web_app.post(
        "/auth/login", data={"username": at_the_provider.identity.email, "password": PASSWORD}
    )
    assert login.status_code == 401


async def test_a_second_sign_in_is_the_same_user(
    browser: httpx.AsyncClient, web_app: httpx.AsyncClient
) -> None:
    first = await web_app.get(
        "/auth/me", headers={"Authorization": f"Bearer {await access_token(browser, web_app)}"}
    )
    second = await web_app.get(
        "/auth/me", headers={"Authorization": f"Bearer {await access_token(browser, web_app)}"}
    )

    assert first.json() == second.json()


async def test_a_verified_email_links_to_the_password_user_who_keeps_the_password(
    browser: httpx.AsyncClient, web_app: httpx.AsyncClient, at_the_provider: FakeIdentityProvider
) -> None:
    email = at_the_provider.identity.email
    registered = await web_app.post(
        "/auth/register", json={"email": email, "full_name": "Ada", "password": PASSWORD}
    )
    assert registered.status_code == 201, registered.text

    token = await access_token(browser, web_app)

    me = await web_app.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["id"] == registered.json()["id"]
    login = await web_app.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert login.status_code == 200


async def test_an_unverified_email_is_refused_and_never_linked_to_the_password_user(
    browser: httpx.AsyncClient,
    web_app: httpx.AsyncClient,
    at_the_provider: FakeIdentityProvider,
    migrated_database_url: str,
) -> None:
    victim = Person.new()
    await web_app.post(
        "/auth/register", json={"email": victim.email, "full_name": "V", "password": PASSWORD}
    )
    at_the_provider.identity = victim.identity(email_verified=False)

    landed = await sign_in_through_the_browser(browser)

    assert landed == f"{WEB_CALLBACK}?error=sso_failed"
    assert (
        stored(
            migrated_database_url,
            "SELECT 1 FROM user_identities WHERE subject = :subject",
            subject=victim.subject,
        )
        == []
    )


async def test_an_inactive_user_cannot_sign_in(
    browser: httpx.AsyncClient,
    web_app: httpx.AsyncClient,
    at_the_provider: FakeIdentityProvider,
    migrated_database_url: str,
) -> None:
    await access_token(browser, web_app)
    engine = sqlalchemy.create_engine(migrated_database_url)
    with engine.begin() as connection:
        connection.execute(
            sqlalchemy.text("UPDATE users SET is_active = false WHERE email = :email"),
            {"email": at_the_provider.identity.email},
        )
    engine.dispose()

    assert await sign_in_through_the_browser(browser) == f"{WEB_CALLBACK}?error=sso_failed"


async def test_state_and_exchange_code_are_single_use_in_redis(
    browser: httpx.AsyncClient, web_app: httpx.AsyncClient
) -> None:
    started = await browser.get("/auth/sso/fake/start")
    binding = started.cookies["sso_binding"]
    at_provider = started.headers["location"]
    first = await browser.get(at_provider)
    code = query_of(first.headers["location"])["code"]

    replayed_state = await browser.get(at_provider, cookies={"sso_binding": binding})
    assert replayed_state.headers["location"] == f"{WEB_CALLBACK}?error=sso_failed"

    assert (await web_app.post("/auth/sso/exchange", json={"code": code})).status_code == 200
    replayed_code = await web_app.post("/auth/sso/exchange", json={"code": code})
    assert replayed_code.status_code == 401
    assert replayed_code.json() == {"detail": "Invalid or expired code"}


async def test_a_callback_in_another_browser_fails(
    browser: httpx.AsyncClient, api_url: str
) -> None:
    started = await browser.get("/auth/sso/fake/start")

    async with httpx.AsyncClient(follow_redirects=False) as another_browser:
        response = await another_browser.get(started.headers["location"])

    assert response.headers["location"] == f"{WEB_CALLBACK}?error=sso_failed"


async def test_unknown_and_disabled_providers_are_a_404(web_app: httpx.AsyncClient) -> None:
    for provider in ("google", "myspace"):
        response = await web_app.get(f"/auth/sso/{provider}/start", follow_redirects=False)
        assert response.status_code == 404
        assert response.json() == {"detail": "Unknown single sign-on provider"}


async def test_concurrent_first_sign_ins_of_one_person_end_as_one_user(
    api_url: str,
    web_app: httpx.AsyncClient,
    at_the_provider: FakeIdentityProvider,
    migrated_database_url: str,
) -> None:
    """Six tabs at once: the unique constraints, not the lookups, make this safe."""

    async def one_tab() -> str:
        async with httpx.AsyncClient(base_url=api_url, follow_redirects=False) as tab:
            return await access_token(tab, web_app)

    tokens = await asyncio.gather(*(one_tab() for _ in range(6)))

    ids = {
        (await web_app.get("/auth/me", headers={"Authorization": f"Bearer {token}"})).json()["id"]
        for token in tokens
    }
    assert len(ids) == 1
    assert stored(
        migrated_database_url,
        "SELECT count(*) FROM users WHERE email = :email",
        email=at_the_provider.identity.email,
    ) == [(1,)]
