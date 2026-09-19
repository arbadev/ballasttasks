import dataclasses

import pytest

from app.application.errors import InvalidCredentialsError
from app.application.use_cases.authenticate_user import AuthenticateUser
from app.application.use_cases.register_user import RegisterUser
from app.domain.user import MAX_PASSWORD_LENGTH, User
from tests.auth_fakes import (
    FakePasswordHasher,
    FakeTokenService,
    InMemoryUserRepository,
    a_user,
)


class CountingHasher(FakePasswordHasher):
    def __init__(self) -> None:
        super().__init__()
        self.work = 0

    def hash(self, password: str) -> str:
        self.work += 1
        return super().hash(password)

    def verify(self, password: str, hashed_password: str) -> bool:
        self.work += 1
        return super().verify(password, hashed_password)


@pytest.fixture
def users() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def hasher() -> CountingHasher:
    return CountingHasher()


@pytest.fixture
def tokens() -> FakeTokenService:
    return FakeTokenService()


@pytest.fixture
async def ada(users: InMemoryUserRepository, hasher: CountingHasher) -> User:
    user = await RegisterUser(users, hasher).execute(
        email="ada@example.com", full_name="Ada Lovelace", password="correct horse"
    )
    hasher.work = 0
    return user


@pytest.fixture
def authenticate(
    users: InMemoryUserRepository, hasher: CountingHasher, tokens: FakeTokenService
) -> AuthenticateUser:
    return AuthenticateUser(users, hasher, tokens)


async def test_valid_credentials_yield_a_token_for_that_user(
    authenticate: AuthenticateUser, tokens: FakeTokenService, ada: User
) -> None:
    token = await authenticate.execute(email="ada@example.com", password="correct horse")

    assert tokens.decode(token) == ada.id


async def test_the_email_is_normalised_before_the_lookup(
    authenticate: AuthenticateUser, tokens: FakeTokenService, ada: User
) -> None:
    token = await authenticate.execute(email=" ADA@Example.com ", password="correct horse")

    assert tokens.decode(token) == ada.id


async def test_unknown_email_and_wrong_password_raise_the_same_error(
    authenticate: AuthenticateUser, ada: User
) -> None:
    with pytest.raises(InvalidCredentialsError) as wrong_password:
        await authenticate.execute(email="ada@example.com", password="wrong")
    with pytest.raises(InvalidCredentialsError) as unknown_email:
        await authenticate.execute(email="nobody@example.com", password="correct horse")
    with pytest.raises(InvalidCredentialsError) as malformed_email:
        await authenticate.execute(email="not-an-email", password="correct horse")

    assert type(wrong_password.value) is type(unknown_email.value) is type(malformed_email.value)
    assert str(wrong_password.value) == str(unknown_email.value) == str(malformed_email.value)


@pytest.mark.parametrize("email", ["a\x00da@example.com", "ada@example.com\x00", "a\x07da@x.co"])
async def test_an_email_with_a_control_character_is_just_another_failed_login(
    authenticate: AuthenticateUser, hasher: CountingHasher, ada: User, email: str
) -> None:
    with pytest.raises(InvalidCredentialsError):
        await authenticate.execute(email=email, password="correct horse")

    assert hasher.work == 1


@pytest.mark.parametrize("email", ["ada@example.com", "nobody@example.com"])
async def test_a_password_longer_than_any_stored_one_fails_before_any_hashing(
    authenticate: AuthenticateUser, hasher: CountingHasher, ada: User, email: str
) -> None:
    with pytest.raises(InvalidCredentialsError) as too_long:
        await authenticate.execute(email=email, password="x" * (MAX_PASSWORD_LENGTH + 1))
    with pytest.raises(InvalidCredentialsError) as wrong_password:
        await authenticate.execute(email="ada@example.com", password="wrong")

    assert str(too_long.value) == str(wrong_password.value)
    assert hasher.work == 1


async def test_a_password_of_the_maximum_length_still_logs_in(
    users: InMemoryUserRepository, hasher: CountingHasher, tokens: FakeTokenService
) -> None:
    password = "x" * MAX_PASSWORD_LENGTH
    user = await RegisterUser(users, hasher).execute(
        email="ada@example.com", full_name="Ada Lovelace", password=password
    )

    token = await AuthenticateUser(users, hasher, tokens).execute(
        email="ada@example.com", password=password
    )

    assert tokens.decode(token) == user.id


async def test_an_inactive_user_cannot_log_in(
    authenticate: AuthenticateUser, users: InMemoryUserRepository
) -> None:
    hasher = FakePasswordHasher()
    dormant = await RegisterUser(InMemoryUserRepository(), hasher).execute(
        email="dormant@example.com", full_name="Dormant", password="correct horse"
    )
    await users.add(dataclasses.replace(dormant, is_active=False))

    with pytest.raises(InvalidCredentialsError):
        await authenticate.execute(email="dormant@example.com", password="correct horse")


async def test_an_unknown_email_costs_as_much_hashing_as_a_wrong_password(
    authenticate: AuthenticateUser, hasher: CountingHasher, ada: User
) -> None:
    """No timing oracle: the expensive step runs whether or not the account exists."""
    with pytest.raises(InvalidCredentialsError):
        await authenticate.execute(email="ada@example.com", password="wrong")
    known_cost, hasher.work = hasher.work, 0

    with pytest.raises(InvalidCredentialsError):
        await authenticate.execute(email="nobody@example.com", password="wrong")

    assert hasher.work == known_cost == 1


@pytest.mark.parametrize("password", ["", "None", "correct horse", "!"])
async def test_a_user_who_has_no_password_cannot_log_in_with_one_and_costs_one_hash(
    authenticate: AuthenticateUser,
    users: InMemoryUserRepository,
    hasher: CountingHasher,
    password: str,
) -> None:
    """Created by single sign-on: no password exists, so none matches, and the answer costs
    what every other failed login costs."""
    await users.add(
        dataclasses.replace(a_user(), email="sso-only@example.com", hashed_password=None)
    )

    with pytest.raises(InvalidCredentialsError) as error:
        await authenticate.execute(email="sso-only@example.com", password=password)

    assert str(error.value) == "Incorrect email or password"
    assert hasher.work == 1
