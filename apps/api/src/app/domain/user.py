"""The User entity. Standard library only: no framework reaches the domain."""

import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Self

MAX_EMAIL_LENGTH = 320
MAX_PASSWORD_LENGTH = 128
FULL_NAME_MAX_LENGTH = 200
ROLE_LABEL_MAX_LENGTH = 60
# The C0 and C1 control characters and DEL, as a regex character-class body. No stored text
# may carry one: PostgreSQL cannot hold NUL at all, and the rest only ever hide in a value.
CONTROL_CHARACTERS = r"\x00-\x1f\x7f-\x9f"
# Deliberately modest: one "@", no whitespace or control character, a dotted domain.
# Deliverability is not a domain rule; identity is, and identity only needs a stable,
# comparable address.
_LOCAL = rf"[^@\s{CONTROL_CHARACTERS}]"
_LABEL = rf"[^@\s.{CONTROL_CHARACTERS}]"
_EMAIL_SHAPE = re.compile(rf"{_LOCAL}+@{_LABEL}+(\.{_LABEL}+)+")
_CONTROL_CHARACTER = re.compile(rf"[{CONTROL_CHARACTERS}]")


class InvalidEmailError(ValueError):
    """The value cannot be used as a user's email address."""

    def __init__(self) -> None:
        super().__init__("Not a valid email address")


class InvalidProfileError(ValueError):
    """The full name or the role label a user asked for cannot be stored."""


def initials_of(full_name: str) -> str:
    """The avatar text: first letter of the first and of the last word, upper-cased.

    A single word gives its first two letters, and a name with no letters at all gives ``?``
    (what the design shows for somebody it does not know).
    """
    words = full_name.split()
    if not words:
        return "?"
    letters = words[0][:2] if len(words) == 1 else words[0][0] + words[-1][0]
    return letters.upper()


def normalise_email(raw: str) -> str:
    """Canonical form used for storage, lookup and uniqueness: trimmed and lower-cased."""
    email = raw.strip().lower()
    if len(email) > MAX_EMAIL_LENGTH or not _EMAIL_SHAPE.fullmatch(email):
        raise InvalidEmailError
    return email


@dataclass(frozen=True, slots=True)
class User:
    id: uuid.UUID
    email: str
    full_name: str
    # None: the user has no password (created by single sign-on) and cannot log in with one.
    hashed_password: str | None = field(repr=False)
    is_active: bool
    created_at: datetime
    # Free text the user writes about themselves ("backend", "owner"). A label for the people
    # list, not an authorisation role: nothing is ever allowed or refused because of it.
    role_label: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "email", normalise_email(self.email))

    @property
    def initials(self) -> str:
        return initials_of(self.full_name)

    def renamed(self, full_name: str) -> Self:
        return replace(self, full_name=_valid_full_name(full_name))

    def with_role_label(self, role_label: str | None) -> Self:
        """``None`` and blank text both clear the label."""
        return replace(self, role_label=_valid_role_label(role_label))


@dataclass(frozen=True, slots=True)
class Person:
    """What one user may see of another: enough for an assignee picker, and no email."""

    id: uuid.UUID
    full_name: str
    role_label: str | None

    @classmethod
    def of(cls, user: User) -> Self:
        return cls(id=user.id, full_name=user.full_name, role_label=user.role_label)

    @property
    def initials(self) -> str:
        return initials_of(self.full_name)


def _valid_full_name(full_name: str) -> str:
    stripped = full_name.strip()
    if not stripped:
        raise InvalidProfileError("full_name must not be blank")
    _check_profile_text("full_name", stripped, FULL_NAME_MAX_LENGTH)
    return stripped


def _valid_role_label(role_label: str | None) -> str | None:
    stripped = None if role_label is None else role_label.strip()
    if not stripped:
        return None
    _check_profile_text("role_label", stripped, ROLE_LABEL_MAX_LENGTH)
    return stripped


def _check_profile_text(field_name: str, text: str, max_length: int) -> None:
    if len(text) > max_length:
        raise InvalidProfileError(f"{field_name} must be at most {max_length} characters")
    if _CONTROL_CHARACTER.search(text):
        raise InvalidProfileError(f"{field_name} must not contain control characters")
