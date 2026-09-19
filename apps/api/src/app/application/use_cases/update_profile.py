from dataclasses import dataclass

from app.application.ports.user_repository import UserRepository
from app.application.unset import UNSET, Unset
from app.domain.user import User


@dataclass(frozen=True, slots=True)
class ProfileChanges:
    """What a user may change about themselves; ``None`` clears the role label."""

    full_name: str | Unset = UNSET
    role_label: str | Unset | None = UNSET


class UpdateProfile:
    """The user is the caller the seam has just authenticated, in this same unit of work."""

    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(self, user: User, changes: ProfileChanges) -> User:
        """Raises ``InvalidProfileError`` before anything is stored."""
        if changes == ProfileChanges():
            return user
        if changes.full_name is not UNSET:
            user = user.renamed(changes.full_name)
        if changes.role_label is not UNSET:
            user = user.with_role_label(changes.role_label)
        await self._users.update(user)
        return user
