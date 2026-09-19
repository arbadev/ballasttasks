"""GET /users (the people list) and PATCH /auth/me (the profile a user edits)."""

import httpx
import pytest

from app.api.schemas.users import PeopleResponse
from tests.api.conftest import AuthFakes
from tests.auth_fakes import a_user

REGISTRATION = {"email": "ada@example.com", "full_name": "Ada Lovelace", "password": "s3cret-pass"}


async def signed_in(client: httpx.AsyncClient) -> dict[str, str]:
    assert (await client.post("/auth/register", json=REGISTRATION)).status_code == 201
    login = await client.post(
        "/auth/login",
        data={"username": REGISTRATION["email"], "password": REGISTRATION["password"]},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --- GET /users --------------------------------------------------------------------------------


async def test_people_are_the_active_users_by_name_with_initials_and_a_role_label(
    task_client: httpx.AsyncClient, auth_fakes: AuthFakes
) -> None:
    tomas = a_user(full_name="Tomas Rey", role_label="frontend")
    andres = a_user(full_name="andres barradas")
    gone = a_user(full_name="Lucia Marin", is_active=False)
    for user in (tomas, andres, gone):
        await auth_fakes.users.add(user)

    response = await task_client.get("/users")

    assert response.status_code == 200
    PeopleResponse.model_validate(response.json())
    assert response.json() == {
        "items": [
            {
                "id": str(andres.id),
                "full_name": "andres barradas",
                "initials": "AB",
                "role_label": None,
            },
            {
                "id": str(tomas.id),
                "full_name": "Tomas Rey",
                "initials": "TR",
                "role_label": "frontend",
            },
        ]
    }


async def test_the_people_list_never_carries_an_email_or_a_hash(
    task_client: httpx.AsyncClient, auth_fakes: AuthFakes
) -> None:
    user = a_user()
    await auth_fakes.users.add(user)

    text = (await task_client.get("/users")).text

    assert user.email not in text
    assert "example.com" not in text
    assert user.hashed_password is not None
    assert user.hashed_password not in text
    assert "email" not in text


async def test_the_people_list_needs_a_signed_in_user(
    anonymous_client: httpx.AsyncClient,
) -> None:
    response = await anonymous_client.get("/users")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


# --- PATCH /auth/me ----------------------------------------------------------------------------


async def test_me_shows_initials_and_no_role_label_until_one_is_set(
    auth_client: httpx.AsyncClient,
) -> None:
    headers = await signed_in(auth_client)

    body = (await auth_client.get("/auth/me", headers=headers)).json()

    assert (body["initials"], body["role_label"]) == ("AL", None)


async def test_a_user_sets_their_name_and_role_label(auth_client: httpx.AsyncClient) -> None:
    headers = await signed_in(auth_client)

    response = await auth_client.patch(
        "/auth/me", headers=headers, json={"full_name": "  Ada King ", "role_label": " backend "}
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["full_name"], body["initials"], body["role_label"]) == (
        "Ada King",
        "AK",
        "backend",
    )
    assert body["email"] == "ada@example.com"
    assert (await auth_client.get("/auth/me", headers=headers)).json() == body
    people = (await auth_client.get("/users", headers=headers)).json()["items"]
    assert [(p["full_name"], p["role_label"]) for p in people] == [("Ada King", "backend")]


async def test_patch_me_is_partial_and_null_clears_the_role_label(
    auth_client: httpx.AsyncClient,
) -> None:
    headers = await signed_in(auth_client)
    await auth_client.patch("/auth/me", headers=headers, json={"role_label": "backend"})

    kept = await auth_client.patch("/auth/me", headers=headers, json={"full_name": "Ada King"})
    cleared = await auth_client.patch("/auth/me", headers=headers, json={"role_label": None})
    blank = await auth_client.patch("/auth/me", headers=headers, json={"role_label": "  "})
    untouched = await auth_client.patch("/auth/me", headers=headers, json={})

    assert (kept.json()["full_name"], kept.json()["role_label"]) == ("Ada King", "backend")
    assert cleared.json()["role_label"] is None
    assert blank.json()["role_label"] is None
    assert untouched.status_code == 200
    assert untouched.json()["full_name"] == "Ada King"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"full_name": None}, id="name null"),
        pytest.param({"full_name": "   "}, id="name blank"),
        pytest.param({"full_name": "x" * 201}, id="name too long"),
        pytest.param({"full_name": "Ada\x00"}, id="name with NUL"),
        pytest.param({"role_label": "x" * 61}, id="label too long"),
        pytest.param({"role_label": "back\x1bend"}, id="label with a control character"),
        pytest.param({"email": "eve@example.com"}, id="email is not editable here"),
        pytest.param({"is_active": False}, id="flags are not editable here"),
        pytest.param({"password": "another-s3cret"}, id="password is not editable here"),
    ],
)
async def test_patch_me_rejects_an_invalid_body_and_changes_nothing(
    auth_client: httpx.AsyncClient, body: dict[str, object]
) -> None:
    headers = await signed_in(auth_client)
    before = (await auth_client.get("/auth/me", headers=headers)).json()

    response = await auth_client.patch("/auth/me", headers=headers, json=body)

    assert response.status_code == 422
    assert "input" not in response.json()["detail"][0]
    assert "another-s3cret" not in response.text
    assert (await auth_client.get("/auth/me", headers=headers)).json() == before


async def test_patch_me_needs_a_valid_token(auth_client: httpx.AsyncClient) -> None:
    anonymous = await auth_client.patch("/auth/me", json={"role_label": "owner"})
    forged = await auth_client.patch(
        "/auth/me", headers={"Authorization": "Bearer nope"}, json={"role_label": "owner"}
    )

    for response in (anonymous, forged):
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
