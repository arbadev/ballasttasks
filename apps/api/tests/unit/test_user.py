import dataclasses
import uuid
from datetime import UTC, datetime

import pytest

from app.domain.user import (
    FULL_NAME_MAX_LENGTH,
    ROLE_LABEL_MAX_LENGTH,
    InvalidEmailError,
    InvalidProfileError,
    Person,
    User,
    initials_of,
    normalise_email,
)


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


# --- the people list: initials, a role label, and a profile the user can edit ----------------


@pytest.mark.parametrize(
    ("full_name", "initials"),
    [
        ("Andres Barradas", "AB"),
        ("Lucía Marín", "LM"),
        ("ada lovelace", "AL"),
        ("Ada King Lovelace", "AL"),
        ("  Tomás   Rey ", "TR"),
        ("Assistant", "AS"),
        ("X", "X"),
        ("élodie", "ÉL"),
        ("", "?"),
        ("   ", "?"),
    ],
)
def test_initials_are_the_first_letters_of_the_first_and_last_name(
    full_name: str, initials: str
) -> None:
    assert initials_of(full_name) == initials


def test_a_user_has_initials_and_no_role_label_until_one_is_set() -> None:
    user = _user(full_name="Ada Lovelace")

    assert user.initials == "AL"
    assert user.role_label is None
    assert _user(role_label="backend").role_label == "backend"


def test_a_profile_change_returns_a_new_user_and_leaves_the_rest_alone() -> None:
    user = _user()

    renamed = user.renamed("  Ada King ")
    labelled = renamed.with_role_label(" backend ")

    assert (renamed.full_name, renamed.role_label) == ("Ada King", None)
    assert (labelled.full_name, labelled.role_label) == ("Ada King", "backend")
    assert user.full_name == "Ada Lovelace"
    assert dataclasses.replace(labelled, full_name=user.full_name, role_label=None) == user


def test_a_role_label_is_cleared_by_none_or_by_blank_text() -> None:
    user = _user(role_label="backend")

    assert user.with_role_label(None).role_label is None
    assert user.with_role_label("   ").role_label is None


@pytest.mark.parametrize(
    "full_name", ["", "   ", "x" * (FULL_NAME_MAX_LENGTH + 1), "Ada\x00", "A\x1bda"]
)
def test_a_blank_overlong_or_control_character_name_is_rejected(full_name: str) -> None:
    with pytest.raises(InvalidProfileError, match="full_name"):
        _user().renamed(full_name)


@pytest.mark.parametrize(
    "role_label", ["x" * (ROLE_LABEL_MAX_LENGTH + 1), "back\x00end", "back\x9bend"]
)
def test_an_overlong_or_control_character_role_label_is_rejected(role_label: str) -> None:
    with pytest.raises(InvalidProfileError, match="role_label"):
        _user().with_role_label(role_label)


def test_a_person_is_what_other_users_may_see_of_a_user() -> None:
    user = _user(full_name="Lucía Marín", role_label="backend")

    person = Person.of(user)

    assert person == Person(id=user.id, full_name="Lucía Marín", role_label="backend")
    assert person.initials == "LM"
    assert {field.name for field in dataclasses.fields(Person)} == {"id", "full_name", "role_label"}
