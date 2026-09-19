import asyncio

from app.application.errors import InvalidCredentialsError
from app.application.ports.password_hasher import PasswordHasher
from app.application.ports.token_service import TokenService
from app.application.ports.user_repository import UserRepository
from app.domain.user import MAX_PASSWORD_LENGTH, InvalidEmailError, normalise_email


class AuthenticateUser:
    """Exchanges an email and password for an access token.

    Every failure is the same ``InvalidCredentialsError``, and an unknown email still pays
    for one hash, so neither the response nor its timing reveals which accounts exist.
    A password longer than any stored one is refused before any hashing, whoever it is
    for.
    """

    def __init__(self, users: UserRepository, hasher: PasswordHasher, tokens: TokenService) -> None:
        self._users = users
        self._hasher = hasher
        self._tokens = tokens

    async def execute(self, *, email: str, password: str) -> str:
        if len(password) > MAX_PASSWORD_LENGTH:
            raise InvalidCredentialsError
        try:
            user = await self._users.get_by_email(normalise_email(email))
        except InvalidEmailError:
            user = None
        if user is None:
            await asyncio.to_thread(self._hasher.hash, password)
            raise InvalidCredentialsError
        verified = await asyncio.to_thread(self._hasher.verify, password, user.hashed_password)
        if not verified or not user.is_active:
            raise InvalidCredentialsError
        return self._tokens.issue(user.id)
