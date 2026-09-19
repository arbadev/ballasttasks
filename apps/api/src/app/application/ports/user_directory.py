import uuid
from typing import Protocol


class UserDirectory(Protocol):
    """The one thing the task use cases may ask about users.

    Deliberately not the ``UserRepository``: assigning a task needs a yes or a no, never a
    ``User``, an email or a password hash.
    """

    async def is_active_user(self, user_id: uuid.UUID) -> bool:
        """``True`` only for a stored user who is active; unknown and inactive are ``False``."""
        ...
