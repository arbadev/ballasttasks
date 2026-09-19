import dataclasses
import logging
import uuid
from datetime import timedelta

import httpx
import pytest

from app.domain.user import MAX_PASSWORD_LENGTH, User
from tests.api.conftest import AuthFakes
from tests.auth_fakes import FakeTokenService

ADA = {"email": "ada@example.com", "full_name": "Ada Lovelace", "password": "correct horse"}
CREDENTIALS = {"username": ADA["email"], "password": ADA["password"]}


async def _register(client: httpx.AsyncClient, **overrides: str) -> httpx.Response:
    return await client.post("/auth/register", json={**ADA, **overrides})


async def _login(client: httpx.AsyncClient, **overrides: str) -> httpx.Response:
    return await client.post("/auth/login", data={**CREDENTIALS, **overrides})


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- POST /auth/register ---------------------------------------------------------------


async def test_register_returns_201_and_the_user_without_any_secret(
    auth_client: httpx.AsyncClient,
) -> None:
    response = await _register(auth_client)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "email", "full_name", "is_active", "created_at"}
    assert uuid.UUID(body["id"])
    assert body["email"] == "ada@example.com"
    assert body["full_name"] == "Ada Lovelace"
    assert body["is_active"] is True
    assert "correct horse" not in response.text


async def test_register_normalises_the_email(auth_client: httpx.AsyncClient) -> None:
    response = await _register(auth_client, email="  Ada@Example.COM ")

    assert response.status_code == 201
    assert response.json()["email"] == "ada@example.com"


async def test_register_stores_a_hash_not_the_password(
    auth_client: httpx.AsyncClient, auth_fakes: AuthFakes
) -> None:
    await _register(auth_client)

    stored = await auth_fakes.users.get_by_email("ada@example.com")
    assert stored is not None
    assert stored.hashed_password != ADA["password"]
    assert auth_fakes.hasher.verify(ADA["password"], stored.hashed_password)


async def test_register_rejects_a_duplicate_email_with_409(
    auth_client: httpx.AsyncClient,
) -> None:
    await _register(auth_client)

    response = await _register(auth_client, email="ADA@example.com", full_name="Impostor")

    assert response.status_code == 409
    assert response.json() == {"detail": "Email already registered"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "not-an-email"},
        {"email": ""},
        {"password": "short"},
        {"password": "x" * 129},
        {"full_name": "   "},
        {"full_name": "x" * 201},
    ],
    ids=["bad-email", "empty-email", "short-password", "long-password", "blank-name", "long-name"],
)
async def test_register_rejects_invalid_input_with_422(
    auth_client: httpx.AsyncClient, overrides: dict[str, str]
) -> None:
    response = await _register(auth_client, **overrides)

    assert response.status_code == 422
    assert ADA["password"] not in response.text


@pytest.mark.parametrize("field", ["email", "full_name", "password"])
@pytest.mark.parametrize(
    "character",
    ["\x00", "\x07", "\x1b", "\x7f", "\x9b"],
    ids=["nul", "bell", "escape", "delete", "c1"],
)
async def test_register_rejects_a_control_character_with_422(
    auth_client: httpx.AsyncClient, auth_fakes: AuthFakes, field: str, character: str
) -> None:
    value = ADA[field][:3] + character + ADA[field][3:]

    response = await _register(auth_client, **{field: value})

    assert response.status_code == 422
    assert [error["loc"] for error in response.json()["detail"]] == [["body", field]]
    assert ADA["password"] not in response.text
    assert await auth_fakes.users.get_by_email(ADA["email"]) is None


@pytest.mark.parametrize("field", ["full_name", "password"])
async def test_register_rejects_a_line_break_inside_a_value_with_422(
    auth_client: httpx.AsyncClient, field: str
) -> None:
    response = await _register(auth_client, **{field: f"{ADA[field]}\nsecond line"})

    assert response.status_code == 422


async def test_register_rejects_a_password_ending_in_a_line_break_with_422(
    auth_client: httpx.AsyncClient,
) -> None:
    response = await _register(auth_client, password=ADA["password"] + "\n")

    assert response.status_code == 422


async def test_register_never_echoes_a_rejected_password(auth_client: httpx.AsyncClient) -> None:
    response = await _register(auth_client, password="hunter2")

    assert response.status_code == 422
    assert "hunter2" not in response.text


async def test_a_validation_error_never_echoes_the_request_body(
    auth_client: httpx.AsyncClient,
) -> None:
    """A missing field makes pydantic report the whole body as ``input``: password included."""
    response = await auth_client.post(
        "/auth/register", json={"full_name": "Ada", "password": "correct horse"}
    )

    assert response.status_code == 422
    assert "correct horse" not in response.text
    assert [error["loc"] for error in response.json()["detail"]] == [["body", "email"]]
    assert all("input" not in error for error in response.json()["detail"])


# --- POST /auth/login ------------------------------------------------------------------


async def test_login_with_the_oauth2_form_returns_a_bearer_token(
    auth_client: httpx.AsyncClient, auth_fakes: AuthFakes
) -> None:
    user_id = (await _register(auth_client)).json()["id"]

    response = await _login(auth_client)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type"}
    assert body["token_type"] == "bearer"
    assert str(auth_fakes.tokens.decode(body["access_token"])) == user_id


async def test_login_accepts_the_email_in_any_case(auth_client: httpx.AsyncClient) -> None:
    await _register(auth_client)

    assert (await _login(auth_client, username="ADA@Example.com")).status_code == 200


async def test_login_failures_are_indistinguishable(auth_client: httpx.AsyncClient) -> None:
    await _register(auth_client)

    wrong_password = await _login(auth_client, password="wrong password")
    unknown_email = await _login(auth_client, username="nobody@example.com")
    malformed_email = await _login(auth_client, username="not-an-email")

    for response in (wrong_password, unknown_email, malformed_email):
        assert response.status_code == 401
        assert response.json() == {"detail": "Incorrect email or password"}
        assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "username",
    ["a\x00da@example.com", "ada@example.com\x00", "a\x07da@example.com", "ada@exam\x7fple.com"],
    ids=["nul-inside", "nul-last", "bell", "delete"],
)
async def test_login_with_a_control_character_in_the_username_is_the_same_401(
    auth_client: httpx.AsyncClient, username: str
) -> None:
    await _register(auth_client)

    response = await _login(auth_client, username=username)

    assert response.status_code == 401
    assert response.json() == {"detail": "Incorrect email or password"}
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_login_with_a_control_character_in_the_password_is_the_same_401(
    auth_client: httpx.AsyncClient,
) -> None:
    await _register(auth_client)

    response = await _login(auth_client, password="correct\x00 horse")

    assert response.status_code == 401
    assert response.json() == {"detail": "Incorrect email or password"}
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_login_with_an_oversized_password_is_the_same_401(
    auth_client: httpx.AsyncClient,
) -> None:
    await _register(auth_client)

    wrong_password = await _login(auth_client, password="wrong password")
    response = await _login(auth_client, password="x" * (MAX_PASSWORD_LENGTH + 1))

    assert response.status_code == wrong_password.status_code == 401
    assert response.json() == wrong_password.json() == {"detail": "Incorrect email or password"}
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_login_rejects_an_inactive_user_like_any_other_failure(
    auth_client: httpx.AsyncClient, auth_fakes: AuthFakes
) -> None:
    dormant = dataclasses.replace(
        await _registered_user(auth_client, auth_fakes),
        id=uuid.uuid4(),
        email="dormant@example.com",
        is_active=False,
    )
    await auth_fakes.users.add(dormant)

    response = await _login(auth_client, username="dormant@example.com")

    assert response.status_code == 401
    assert response.json() == {"detail": "Incorrect email or password"}


async def test_login_requires_the_form_not_json(auth_client: httpx.AsyncClient) -> None:
    await _register(auth_client)

    response = await auth_client.post("/auth/login", json=CREDENTIALS)

    assert response.status_code == 422


# --- GET /auth/me ----------------------------------------------------------------------


async def _registered_user(client: httpx.AsyncClient, fakes: AuthFakes) -> User:
    user_id = uuid.UUID((await _register(client)).json()["id"])
    user = await fakes.users.get_by_id(user_id)
    assert user is not None
    return user


async def test_me_returns_the_user_behind_the_token(auth_client: httpx.AsyncClient) -> None:
    registered = (await _register(auth_client)).json()
    token = (await _login(auth_client)).json()["access_token"]

    response = await auth_client.get("/auth/me", headers=_bearer(token))

    assert response.status_code == 200
    assert response.json() == registered


@pytest.mark.parametrize(
    ("headers", "detail"),
    [
        ({}, "Not authenticated"),
        ({"Authorization": "Basic YWRhOmh1bnRlcjI="}, "Not authenticated"),
        ({"Authorization": "Bearer garbage"}, "Could not validate credentials"),
    ],
    ids=["no-header", "wrong-scheme", "garbage-token"],
)
async def test_me_without_a_valid_token_is_401_with_a_bearer_challenge(
    auth_client: httpx.AsyncClient, headers: dict[str, str], detail: str
) -> None:
    response = await auth_client.get("/auth/me", headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": detail}
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_me_with_an_expired_token_is_401(
    auth_client: httpx.AsyncClient, auth_fakes: AuthFakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _registered_user(auth_client, auth_fakes)
    monkeypatch.setattr(auth_fakes.tokens, "_expires_in", timedelta(seconds=-1))

    response = await auth_client.get("/auth/me", headers=_bearer(auth_fakes.tokens.issue(user.id)))

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


async def test_me_for_a_token_whose_user_is_gone_or_inactive_is_401(
    auth_client: httpx.AsyncClient, auth_fakes: AuthFakes
) -> None:
    user = await _registered_user(auth_client, auth_fakes)
    dormant = dataclasses.replace(
        user, id=uuid.uuid4(), email="dormant@example.com", is_active=False
    )
    await auth_fakes.users.add(dormant)

    for user_id in (uuid.uuid4(), dormant.id):
        response = await auth_client.get(
            "/auth/me", headers=_bearer(auth_fakes.tokens.issue(user_id))
        )

        assert response.status_code == 401
        assert response.json() == {"detail": "Could not validate credentials"}
        assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_a_token_from_another_issuer_is_401(
    auth_client: httpx.AsyncClient, auth_fakes: AuthFakes
) -> None:
    user = await _registered_user(auth_client, auth_fakes)

    response = await auth_client.get("/auth/me", headers=_bearer(FakeTokenService().issue(user.id)))

    assert response.status_code == 401


# --- hygiene ---------------------------------------------------------------------------


async def test_health_endpoints_stay_public(auth_client: httpx.AsyncClient) -> None:
    assert (await auth_client.get("/health")).status_code == 200
    assert (await auth_client.get("/health/ready")).status_code == 200


async def test_passwords_hashes_and_tokens_never_reach_the_logs(
    auth_client: httpx.AsyncClient, auth_fakes: AuthFakes, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    user = await _registered_user(auth_client, auth_fakes)
    token = (await _login(auth_client)).json()["access_token"]
    await auth_client.get("/auth/me", headers=_bearer(token))
    await _login(auth_client, password="a wrong password")

    for secret in (ADA["password"], user.hashed_password, token, "a wrong password"):
        assert secret not in caplog.text
