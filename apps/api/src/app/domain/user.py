"""The User entity. Standard library only: no framework reaches the domain."""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime

MAX_EMAIL_LENGTH = 320
MAX_PASSWORD_LENGTH = 128
# The C0 and C1 control characters and DEL, as a regex character-class body. No stored text
# may carry one: PostgreSQL cannot hold NUL at all, and the rest only ever hide in a value.
CONTROL_CHARACTERS = r"\x00-\x1f\x7f-\x9f"
# Deliberately modest: one "@", no whitespace or control character, a dotted domain.
# Deliverability is not a domain rule; identity is, and identity only needs a stable,
# comparable address.
_LOCAL = rf"[^@\s{CONTROL_CHARACTERS}]"
_LABEL = rf"[^@\s.{CONTROL_CHARACTERS}]"
_EMAIL_SHAPE = re.compile(rf"{_LOCAL}+@{_LABEL}+(\.{_LABEL}+)+")


class InvalidEmailError(ValueError):
    """The value cannot be used as a user's email address."""

    def __init__(self) -> None:
        super().__init__("Not a valid email address")


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "email", normalise_email(self.email))
