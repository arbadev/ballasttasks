"""The seam other features build on: ``app.api.security.get_current_user_id``."""

import uuid

import httpx
from fastapi import FastAPI

from app.api.security import CurrentUserId, get_current_user_id
from tests.api.conftest import AuthFakes

ADA = {"email": "ada@example.com", "full_name": "Ada Lovelace", "password": "correct horse"}


def _add_probe(app: FastAPI) -> None:
    @app.get("/probe")
    async def probe(user_id: CurrentUserId) -> dict[str, str]:
        assert isinstance(user_id, uuid.UUID)
        return {"user_id": str(user_id)}


async def test_a_route_receives_the_token_owners_id_as_a_uuid(
    auth_app: FastAPI, auth_client: httpx.AsyncClient
) -> None:
    _add_probe(auth_app)
    user_id = (await auth_client.post("/auth/register", json=ADA)).json()["id"]
    login = await auth_client.post(
        "/auth/login", data={"username": ADA["email"], "password": ADA["password"]}
    )

    response = await auth_client.get(
        "/probe", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )

    assert response.status_code == 200
    assert response.json() == {"user_id": user_id}


async def test_a_route_behind_the_seam_is_401_without_a_token(
    auth_app: FastAPI, auth_client: httpx.AsyncClient
) -> None:
    _add_probe(auth_app)

    response = await auth_client.get("/probe")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_an_inactive_users_token_does_not_pass_the_seam(
    auth_app: FastAPI, auth_client: httpx.AsyncClient, auth_fakes: AuthFakes
) -> None:
    _add_probe(auth_app)

    response = await auth_client.get(
        "/probe", headers={"Authorization": f"Bearer {auth_fakes.tokens.issue(uuid.uuid4())}"}
    )

    assert response.status_code == 401


async def test_other_features_can_override_the_seam_in_their_own_tests(
    auth_app: FastAPI, auth_client: httpx.AsyncClient
) -> None:
    _add_probe(auth_app)
    someone = uuid.uuid4()
    auth_app.dependency_overrides[get_current_user_id] = lambda: someone

    response = await auth_client.get("/probe")

    assert response.json() == {"user_id": str(someone)}
