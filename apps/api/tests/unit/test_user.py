import dataclasses
import uuid
from datetime import UTC, datetime

import pytest

from app.domain.user import InvalidEmailError, User, normalise_email


def _user(**overrides: object) -> User:
    fields: dict[str, object] = {
        "id": uuid.uuid4(),
        "email": "ada@example.com",
        "full_name": "Ada Lovelace",
        "hashed_password": "hash",
        "is_active": True,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    return User(**{**fields, **overrides})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ada@example.com", "ada@example.com"),
        ("  Ada@Example.COM ", "ada@example.com"),
        ("ADA.LOVELACE+tasks@EXAMPLE.co.uk", "ada.lovelace+tasks@example.co.uk"),
    ],
)
def test_email_is_normalised_to_trimmed_lower_case(raw: str, expected: str) -> None:
    assert normalise_email(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "ada", "ada@", "@example.com", "ada@example", "a da@example.com", "a@b@c.com"],
)
def test_a_malformed_email_is_rejected(raw: str) -> None:
    with pytest.raises(InvalidEmailError):
        normalise_email(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "a\x00@example.com",
        "ada@exam\x00ple.com",
        "ada@example.com\x00",
        "\x00ada@example.com",
        "a\x07da@example.com",
        "a\x1bda@example.com",
        "ada@exam\x7fple.com",
        "ada@example.c\x9bom",
    ],
    ids=["nul-local", "nul-domain", "nul-last", "nul-first", "bell", "escape", "delete", "c1"],
)
def test_an_email_with_a_control_character_is_rejected(raw: str) -> None:
    with pytest.raises(InvalidEmailError):
        normalise_email(raw)


@pytest.mark.parametrize("code_point", [*range(0x20), *range(0x7F, 0xA0)])
def test_no_control_character_survives_normalisation(code_point: int) -> None:
    with pytest.raises(InvalidEmailError):
        normalise_email(f"a{chr(code_point)}da@example.com")


def test_an_over_long_email_is_rejected() -> None:
    with pytest.raises(InvalidEmailError):
        normalise_email("a" * 320 + "@example.com")


def test_user_always_holds_a_normalised_email() -> None:
    assert _user(email=" Ada@Example.com ").email == "ada@example.com"


def test_user_rejects_a_malformed_email() -> None:
    with pytest.raises(InvalidEmailError):
        _user(email="not-an-email")


def test_user_is_immutable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _user().is_active = False  # type: ignore[misc]


def test_user_repr_never_shows_the_password_hash() -> None:
    assert "super-secret-hash" not in repr(_user(hashed_password="super-secret-hash"))
