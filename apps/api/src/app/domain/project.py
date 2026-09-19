"""The Project entity: what tasks belong to, and where their keys come from.

Standard library only. The key is fixed at creation: every task created in the project
carries it in its own immutable key, so changing it would orphan those keys.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Self

from app.domain.task_key import KEY_PREFIX_MAX_LENGTH, KEY_PREFIX_MIN_LENGTH, is_key_prefix

PROJECT_NAME_MAX_LENGTH = 100
PROJECT_COLOR_MAX_LENGTH = 32
# A design token name such as ``acc`` or ``fg-3``; how it is drawn is the frontend's business.
_COLOR_TOKEN = re.compile(rf"[a-z0-9-]{{1,{PROJECT_COLOR_MAX_LENGTH}}}")

# The project every database has: the migration creates it and gives it the tasks that
# existed before projects did. A task created without a project lands here, as in the design.
DEFAULT_PROJECT_ID: Final = uuid.UUID("00000000-0000-4000-8000-000000000001")
DEFAULT_PROJECT_NAME: Final = "Inbox"
DEFAULT_PROJECT_KEY: Final = "IN"


class InvalidProjectError(ValueError):
    """A project would break one of its invariants."""


@dataclass(slots=True)
class Project:
    id: uuid.UUID
    name: str
    key: str
    color: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        self.name = _valid_name(self.name)
        if not is_key_prefix(self.key):
            raise InvalidProjectError(
                f"key must be {KEY_PREFIX_MIN_LENGTH} to {KEY_PREFIX_MAX_LENGTH} upper-case letters"
            )
        _check_color(self.color)
        for moment in (self.created_at, self.updated_at):
            _check_aware(moment)

    @classmethod
    def create(
        cls,
        *,
        project_id: uuid.UUID,
        name: str,
        key: str,
        now: datetime,
        color: str | None = None,
    ) -> Self:
        return cls(id=project_id, name=name, key=key, color=color, created_at=now, updated_at=now)

    def rename(self, name: str, *, now: datetime) -> None:
        valid_name = _valid_name(name)
        self._touch(now)
        self.name = valid_name

    def recolor(self, color: str | None, *, now: datetime) -> None:
        _check_color(color)
        self._touch(now)
        self.color = color

    def _touch(self, now: datetime) -> None:
        _check_aware(now)
        self.updated_at = now


def _valid_name(name: str) -> str:
    if "\x00" in name:
        raise InvalidProjectError("name must not contain the NUL character")
    stripped = name.strip()
    if not stripped:
        raise InvalidProjectError("name must not be blank")
    if len(stripped) > PROJECT_NAME_MAX_LENGTH:
        raise InvalidProjectError(f"name must be at most {PROJECT_NAME_MAX_LENGTH} characters")
    return stripped


def _check_color(color: str | None) -> None:
    if color is not None and _COLOR_TOKEN.fullmatch(color) is None:
        raise InvalidProjectError(
            f"color must be a token of 1 to {PROJECT_COLOR_MAX_LENGTH} lower-case letters, "
            "digits and hyphens"
        )


def _check_aware(moment: datetime) -> None:
    if moment.utcoffset() is None:
        raise InvalidProjectError("timestamps must be timezone-aware")
