import uuid
from typing import Protocol


class UserDirectory(Protocol):
    """The little the task use cases may ask about users.

    Deliberately not the ``UserRepository``: assigning a task needs a yes or a no, and the
    activity log needs a name to write ("Assigned to Lucía Marín"); neither needs a ``User``,
    an email or a password hash.
    """

    async def is_active_user(self, user_id: uuid.UUID) -> bool:
        """``True`` only for a stored user who is active; unknown and inactive are ``False``."""
        ...

    async def full_name_of(self, user_id: uuid.UUID) -> str | None:
        """The full name of a stored user, active or not; ``None`` for an unknown id."""
        ...
