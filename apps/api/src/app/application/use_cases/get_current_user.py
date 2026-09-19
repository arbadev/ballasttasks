from app.application.errors import UserNotActiveError
from app.application.ports.token_service import TokenService
from app.application.ports.user_repository import UserRepository
from app.domain.user import User


class GetCurrentUser:
    """Resolves an access token to its active user.

    The user is re-read on every call, so deactivating or deleting an account takes
    effect immediately, without waiting for its tokens to expire.
    """

    def __init__(self, users: UserRepository, tokens: TokenService) -> None:
        self._users = users
        self._tokens = tokens

    async def execute(self, token: str) -> User:
        user = await self._users.get_by_id(self._tokens.decode(token))
        if user is None or not user.is_active:
            raise UserNotActiveError
        return user
