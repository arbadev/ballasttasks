import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.application.errors import InvalidTokenError


class JwtTokenService:
    """Signed JWT access tokens (PyJWT) carrying only ``sub``, ``iat`` and ``exp``.

    Decoding pins the one configured algorithm, which is what defeats ``alg=none`` and
    algorithm-confusion tokens, and requires ``sub`` and ``exp`` to be present.
    """

    def __init__(self, secret: str, *, algorithm: str, expires_in: timedelta) -> None:
        self._secret = secret
        self._algorithm = algorithm
        self._expires_in = expires_in

    def issue(self, user_id: uuid.UUID) -> str:
        now = datetime.now(UTC)
        claims = {"sub": str(user_id), "iat": now, "exp": now + self._expires_in}
        return jwt.encode(claims, self._secret, algorithm=self._algorithm)

    def decode(self, token: str) -> uuid.UUID:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                options={"require": ["sub", "exp"]},
            )
            return uuid.UUID(claims["sub"])
        except (jwt.InvalidTokenError, ValueError) as error:
            raise InvalidTokenError from error
