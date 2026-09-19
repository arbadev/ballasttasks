import uuid
from typing import Protocol


class TokenService(Protocol):
    """Issues and reads access tokens that carry nothing but a user id."""

    def issue(self, user_id: uuid.UUID) -> str: ...

    def decode(self, token: str) -> uuid.UUID:
        """Return the user id the token was issued for.

        Raises ``InvalidTokenError`` when the token is malformed, was not issued by this
        service, or has expired.
        """
        ...
