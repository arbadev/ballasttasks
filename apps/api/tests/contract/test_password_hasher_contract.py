"""Contract every PasswordHasher adapter must honour (Liskov).

Registering a new adapter = one new factory + one line in ``ADAPTERS``. The fake used by
the unit and API tests runs the same suite, so tests built on it stay truthful.
"""

from collections.abc import Callable

import pytest
from app.infrastructure.security.argon2_password_hasher import Argon2PasswordHasher

from app.application.ports.password_hasher import PasswordHasher
from tests.auth_fakes import FakePasswordHasher

AdapterFactory = Callable[[], PasswordHasher]

ADAPTERS = [
    pytest.param(FakePasswordHasher, id="fake"),
    pytest.param(Argon2PasswordHasher, id="argon2"),
]


@pytest.mark.parametrize("factory", ADAPTERS)
def test_the_hash_is_a_string_that_does_not_contain_the_password(factory: AdapterFactory) -> None:
    hashed = factory().hash("correct horse battery staple")

    assert isinstance(hashed, str)
    assert hashed != "correct horse battery staple"


@pytest.mark.parametrize("factory", ADAPTERS)
def test_the_right_password_verifies(factory: AdapterFactory) -> None:
    hasher = factory()

    assert hasher.verify("correct horse", hasher.hash("correct horse")) is True


@pytest.mark.parametrize("factory", ADAPTERS)
def test_a_wrong_password_does_not_verify(factory: AdapterFactory) -> None:
    hasher = factory()

    assert hasher.verify("Correct horse", hasher.hash("correct horse")) is False
    assert hasher.verify("", hasher.hash("correct horse")) is False


@pytest.mark.parametrize("factory", ADAPTERS)
def test_hashing_is_salted(factory: AdapterFactory) -> None:
    hasher = factory()

    assert hasher.hash("correct horse") != hasher.hash("correct horse")


@pytest.mark.parametrize("factory", ADAPTERS)
def test_a_hash_verifies_on_another_instance(factory: AdapterFactory) -> None:
    assert factory().verify("correct horse", factory().hash("correct horse")) is True


@pytest.mark.parametrize("factory", ADAPTERS)
@pytest.mark.parametrize("stored", ["", "not-a-hash", "$argon2id$broken", "plain:correct horse"])
def test_verify_returns_false_and_never_raises_on_a_malformed_hash(
    factory: AdapterFactory, stored: str
) -> None:
    assert factory().verify("correct horse", stored) is False


@pytest.mark.parametrize("factory", ADAPTERS)
def test_non_ascii_and_long_passwords_round_trip(factory: AdapterFactory) -> None:
    hasher = factory()
    password = "contraseña-🔐-" + "x" * 200

    assert hasher.verify(password, hasher.hash(password)) is True


def test_the_real_adapter_uses_argon2id() -> None:
    assert Argon2PasswordHasher().hash("correct horse").startswith("$argon2id$")
