"""The human key of a task: ``<PREFIX>-<NN>``, such as ``BT-04``.

The prefix is the key of the project the task was created in; the number is that project's
next one, handed out by the ``ProjectRepository``. Standard library only.
"""

import re
from dataclasses import dataclass
from typing import Self

KEY_PREFIX_MIN_LENGTH = 2
KEY_PREFIX_MAX_LENGTH = 5
# ``[A-Z]`` and ``[0-9]``, not ``\w`` or ``\d``: those also match letters and digits outside
# ASCII. ``fullmatch``, because ``$`` would let a trailing newline through.
_PREFIX = re.compile(rf"[A-Z]{{{KEY_PREFIX_MIN_LENGTH},{KEY_PREFIX_MAX_LENGTH}}}")
_KEY = re.compile(rf"([A-Za-z]{{{KEY_PREFIX_MIN_LENGTH},{KEY_PREFIX_MAX_LENGTH}}})-([0-9]{{1,9}})")


class InvalidTaskKeyError(ValueError):
    """The text or the parts cannot be a task key."""


def is_key_prefix(text: str) -> bool:
    """2 to 5 upper-case ASCII letters: the rule for a project key."""
    return _PREFIX.fullmatch(text) is not None


@dataclass(frozen=True, slots=True)
class TaskKey:
    prefix: str
    number: int

    def __post_init__(self) -> None:
        if not is_key_prefix(self.prefix):
            raise InvalidTaskKeyError(
                f"a key prefix is {KEY_PREFIX_MIN_LENGTH} to {KEY_PREFIX_MAX_LENGTH} "
                "upper-case letters"
            )
        if self.number < 1:
            raise InvalidTaskKeyError("a key number starts at 1")

    def __str__(self) -> str:
        """Canonical form: the number is padded to two digits, as the design shows it."""
        return f"{self.prefix}-{self.number:02d}"

    @classmethod
    def parse(cls, text: str) -> Self:
        """Reads what a person may type: any case, any padding (``bt-4`` is ``BT-04``)."""
        match = _KEY.fullmatch(text)
        if match is None:
            raise InvalidTaskKeyError(f"{text!r} is not a task key such as BT-04")
        return cls(match.group(1).upper(), int(match.group(2)))
