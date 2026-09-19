from typing import Protocol


class PasswordHasher(Protocol):
    """One-way, salted password hashing. Both calls are CPU-bound and synchronous."""

    def hash(self, password: str) -> str:
        """Return a self-describing hash; two calls with one password differ (salt)."""
        ...

    def verify(self, password: str, hashed_password: str) -> bool:
        """True only when ``password`` produced ``hashed_password``. Must never raise."""
        ...
