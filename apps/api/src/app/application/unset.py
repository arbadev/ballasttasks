"""The difference between "not mentioned" and "set to nothing" in a partial update."""

from enum import Enum
from typing import Final


class Unset(Enum):
    """Marks a field the caller did not mention; ``None`` means "clear it"."""

    UNSET = "unset"


UNSET: Final = Unset.UNSET
