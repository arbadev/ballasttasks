import uuid
from datetime import UTC, datetime

import pytest

from app.application.errors import EmailAlreadyRegisteredError
from app.application.use_cases.register_user import RegisterUser
from app.domain.user import InvalidEmailError
from tests.auth_fakes import FakePasswordHasher, InMemoryUserRepository

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


@pytest.fixture
def users() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def register(users: InMemoryUserRepository) -> RegisterUser:
    return RegisterUser(users, FakePasswordHasher(), clock=lambda: NOW)


async def test_registers_an_active_user_with_a_generated_id(
    register: RegisterUser, users: InMemoryUserRepository
) -> None:
    user = await register.execute(
        email="ada@example.com", full_name="Ada Lovelace", password="correct horse"
    )

    assert isinstance(user.id, uuid.UUID)
    assert user.email == "ada@example.com"
    assert user.full_name == "Ada Lovelace"
    assert user.is_active is True
    assert user.created_at == NOW
    assert await users.get_by_id(user.id) == user


async def test_stores_a_hash_and_never_the_password(register: RegisterUser) -> None:
    user = await register.execute(
        email="ada@example.com", full_name="Ada Lovelace", password="correct horse"
    )

    assert user.hashed_password != "correct horse"
    assert FakePasswordHasher().verify("correct horse", user.hashed_password)


async def test_normalises_the_email_and_trims_the_name(register: RegisterUser) -> None:
    user = await register.execute(
        email="  Ada@Example.COM ", full_name="  Ada Lovelace ", password="correct horse"
    )

    assert user.email == "ada@example.com"
    assert user.full_name == "Ada Lovelace"


async def test_rejects_a_duplicate_email_whatever_its_case(register: RegisterUser) -> None:
    await register.execute(email="ada@example.com", full_name="Ada", password="correct horse")

    with pytest.raises(EmailAlreadyRegisteredError):
        await register.execute(email="ADA@example.com", full_name="Other", password="another one")


async def test_a_duplicate_that_slips_past_the_lookup_is_still_rejected() -> None:
    """Two concurrent registrations: the repository's uniqueness rule is the last word."""

    class BlindLookup(InMemoryUserRepository):
        async def get_by_email(self, email: str) -> None:
            return None

    register = RegisterUser(BlindLookup(), FakePasswordHasher())
    await register.execute(email="ada@example.com", full_name="Ada", password="correct horse")

    with pytest.raises(EmailAlreadyRegisteredError):
        await register.execute(email="ada@example.com", full_name="Ada", password="correct horse")


async def test_rejects_a_malformed_email(register: RegisterUser) -> None:
    with pytest.raises(InvalidEmailError):
        await register.execute(email="nope", full_name="Ada", password="correct horse")
