from argon2 import PasswordHasher as Argon2
from argon2.exceptions import Argon2Error, InvalidHashError


class Argon2PasswordHasher:
    """Argon2id with the library's defaults (the RFC 9106 low-memory profile).

    The parameters and the salt travel inside the hash, so they can be raised later
    without invalidating stored passwords.
    """

    def __init__(self) -> None:
        self._argon2 = Argon2()

    def hash(self, password: str) -> str:
        return self._argon2.hash(password)

    def verify(self, password: str, hashed_password: str) -> bool:
        try:
            return self._argon2.verify(hashed_password, password)
        except Argon2Error, InvalidHashError:
            return False
