"""Contract every TokenService adapter must honour (Liskov), plus JWT-specific attacks.

Registering a new adapter = one new factory + one line in ``ADAPTERS``.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

import jwt
import pytest
from app.infrastructure.security.jwt_token_service import JwtTokenService

from app.application.errors import InvalidTokenError
from app.application.ports.token_service import TokenService
from tests.auth_fakes import FakeTokenService

SECRET = "contract-suite-secret-of-at-least-32-bytes"
OTHER_SECRET = "a-different-secret-of-at-least-32-bytes!!"
HALF_HOUR = timedelta(minutes=30)


class AdapterFactory(Protocol):
    def __call__(
        self, *, secret: str = SECRET, expires_in: timedelta = HALF_HOUR
    ) -> TokenService: ...


def fake(*, secret: str = SECRET, expires_in: timedelta = HALF_HOUR) -> TokenService:
    return FakeTokenService(expires_in=expires_in)


def jwt_hs256(*, secret: str = SECRET, expires_in: timedelta = HALF_HOUR) -> TokenService:
    return JwtTokenService(secret, algorithm="HS256", expires_in=expires_in)


ADAPTERS = [pytest.param(fake, id="fake"), pytest.param(jwt_hs256, id="jwt-hs256")]


@pytest.mark.parametrize("factory", ADAPTERS)
def test_a_token_decodes_to_the_user_it_was_issued_for(factory: AdapterFactory) -> None:
    tokens = factory()
    ada, grace = uuid.uuid4(), uuid.uuid4()

    ada_token, grace_token = tokens.issue(ada), tokens.issue(grace)

    assert isinstance(ada_token, str)
    assert tokens.decode(ada_token) == ada
    assert tokens.decode(grace_token) == grace


@pytest.mark.parametrize("factory", ADAPTERS)
@pytest.mark.parametrize("token", ["", "garbage", "a.b.c", "Bearer x"])
def test_a_malformed_token_is_invalid(factory: AdapterFactory, token: str) -> None:
    with pytest.raises(InvalidTokenError):
        factory().decode(token)


@pytest.mark.parametrize("factory", ADAPTERS)
def test_an_expired_token_is_invalid(factory: AdapterFactory) -> None:
    tokens = factory(expires_in=timedelta(seconds=-1))

    with pytest.raises(InvalidTokenError):
        tokens.decode(tokens.issue(uuid.uuid4()))


@pytest.mark.parametrize("factory", ADAPTERS)
def test_a_token_from_a_service_with_another_secret_is_invalid(factory: AdapterFactory) -> None:
    foreign = factory(secret=OTHER_SECRET).issue(uuid.uuid4())

    with pytest.raises(InvalidTokenError):
        factory().decode(foreign)


@pytest.mark.parametrize("factory", ADAPTERS)
def test_a_tampered_token_is_invalid(factory: AdapterFactory) -> None:
    tokens = factory()
    token = tokens.issue(uuid.uuid4())

    with pytest.raises(InvalidTokenError):
        tokens.decode(token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB"))


def _claims(**overrides: object) -> dict[str, object]:
    now = datetime.now(UTC)
    return {"sub": str(uuid.uuid4()), "iat": now, "exp": now + HALF_HOUR, **overrides}


def test_jwt_carries_only_the_subject_and_its_validity_window() -> None:
    user_id = uuid.uuid4()
    token = jwt_hs256().issue(user_id)

    claims = jwt.decode(token, SECRET, algorithms=["HS256"])

    assert set(claims) == {"sub", "iat", "exp"}
    assert claims["sub"] == str(user_id)
    assert claims["exp"] - claims["iat"] == HALF_HOUR.total_seconds()


def test_jwt_with_alg_none_is_invalid() -> None:
    unsigned = jwt.encode(_claims(), key="", algorithm="none")

    with pytest.raises(InvalidTokenError):
        jwt_hs256().decode(unsigned)


def test_jwt_signed_with_another_algorithm_is_invalid() -> None:
    other_algorithm = jwt.encode(_claims(), SECRET, algorithm="HS512")

    with pytest.raises(InvalidTokenError):
        jwt_hs256().decode(other_algorithm)


@pytest.mark.parametrize("missing", ["sub", "exp"])
def test_jwt_without_a_required_claim_is_invalid(missing: str) -> None:
    claims = _claims()
    del claims[missing]

    with pytest.raises(InvalidTokenError):
        jwt_hs256().decode(jwt.encode(claims, SECRET, algorithm="HS256"))


def test_jwt_whose_subject_is_not_a_uuid_is_invalid() -> None:
    with pytest.raises(InvalidTokenError):
        jwt_hs256().decode(jwt.encode(_claims(sub="42"), SECRET, algorithm="HS256"))
