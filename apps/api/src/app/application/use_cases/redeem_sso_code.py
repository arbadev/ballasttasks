import uuid

from app.application.errors import InvalidSsoCodeError
from app.application.ports.one_time_store import OneTimeStore
from app.application.ports.token_service import TokenService
from app.application.ports.user_repository import UserRepository
from app.application.sso import MAX_SECRET_LENGTH, exchange_code_key


class RedeemSsoCode:
    """Swaps the one-time exchange code for the same access token a password login issues.

    Taking the code deletes it, so it works once. Every failure is the same
    ``InvalidSsoCodeError``: unknown, used, expired, or a user who stopped being active in
    the seconds since the callback.
    """

    def __init__(self, store: OneTimeStore, users: UserRepository, tokens: TokenService) -> None:
        self._store = store
        self._users = users
        self._tokens = tokens

    async def execute(self, code: str) -> str:
        if not code or len(code) > MAX_SECRET_LENGTH:
            raise InvalidSsoCodeError
        user_id = await self._store.take(exchange_code_key(code))
        if user_id is None:
            raise InvalidSsoCodeError
        user = await self._users.get_by_id(uuid.UUID(user_id))
        if user is None or not user.is_active:
            raise InvalidSsoCodeError
        return self._tokens.issue(user.id)
