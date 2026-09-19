from collections.abc import Sequence
from typing import Protocol

from app.domain.user import Person


class PeopleDirectory(Protocol):
    """Who a task can be given to, as other users may see them.

    Separate from ``UserDirectory`` on purpose: the task use cases need a yes or a no about
    one id, the assignee picker needs names, and neither has to carry the other. A ``Person``
    has no email and no password hash, so neither can leak through this port.
    """

    async def list_active(self) -> Sequence[Person]:
        """Every active user, by full name whatever the case, then by id."""
        ...
