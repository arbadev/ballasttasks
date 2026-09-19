"""The User entity. Standard library only: no framework reaches the domain."""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime

MAX_EMAIL_LENGTH = 320
# Deliberately modest: one "@", no whitespace, a dotted domain. Deliverability is not a
# domain rule; identity is, and identity only needs a stable, comparable address.
_EMAIL_SHAPE = re.compile(r"[^@\s]+@[^@\s.]+(\.[^@\s.]+)+")


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
    hashed_password: str = field(repr=False)
    is_active: bool
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "email", normalise_email(self.email))
