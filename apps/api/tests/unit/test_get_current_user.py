import dataclasses
import uuid
from datetime import timedelta

import pytest
from app.application.errors import AuthenticationError, InvalidTokenError, UserNotActiveError
from app.application.use_cases.get_current_user import GetCurrentUser
from app.application.use_cases.register_user import RegisterUser
from app.domain.user import User

from tests.auth_fakes import FakePasswordHasher, FakeTokenService, InMemoryUserRepository


@pytest.fixture
def users() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def tokens() -> FakeTokenService:
    return FakeTokenService()


@pytest.fixture
async def ada(users: InMemoryUserRepository) -> User:
    return await RegisterUser(users, FakePasswordHasher()).execute(
        email="ada@example.com", full_name="Ada Lovelace", password="correct horse"
    )


async def test_a_valid_token_resolves_to_its_user(
    users: InMemoryUserRepository, tokens: FakeTokenService, ada: User
) -> None:
    user = await GetCurrentUser(users, tokens).execute(tokens.issue(ada.id))

    assert user == ada


async def test_a_garbage_token_is_rejected(
    users: InMemoryUserRepository, tokens: FakeTokenService
) -> None:
    with pytest.raises(InvalidTokenError):
        await GetCurrentUser(users, tokens).execute("garbage")


async def test_an_expired_token_is_rejected(users: InMemoryUserRepository, ada: User) -> None:
    expired = FakeTokenService(expires_in=timedelta(seconds=-1))

    with pytest.raises(InvalidTokenError):
        await GetCurrentUser(users, expired).execute(expired.issue(ada.id))


async def test_a_token_for_a_user_that_no_longer_exists_is_rejected(
    users: InMemoryUserRepository, tokens: FakeTokenService
) -> None:
    with pytest.raises(UserNotActiveError):
        await GetCurrentUser(users, tokens).execute(tokens.issue(uuid.uuid4()))


async def test_a_token_for_an_inactive_user_is_rejected(
    users: InMemoryUserRepository, tokens: FakeTokenService, ada: User
) -> None:
    dormant = dataclasses.replace(
        ada, id=uuid.uuid4(), email="dormant@example.com", is_active=False
    )
    await users.add(dormant)

    with pytest.raises(UserNotActiveError):
        await GetCurrentUser(users, tokens).execute(tokens.issue(dormant.id))


def test_every_failure_is_an_authentication_error() -> None:
    assert issubclass(InvalidTokenError, AuthenticationError)
    assert issubclass(UserNotActiveError, AuthenticationError)
