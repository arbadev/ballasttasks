"""Errors the use cases and ports raise. The HTTP layer maps them to status codes."""


class EmailAlreadyRegisteredError(Exception):
    """A user with this (normalised) email already exists."""

    def __init__(self, email: str) -> None:
        super().__init__(f"Email {email!r} is already registered")
        self.email = email


class AuthenticationError(Exception):
    """The caller could not be identified. Subclasses never say more than the HTTP 401 may."""


class InvalidCredentialsError(AuthenticationError):
    """Unknown email, wrong password or inactive account: deliberately indistinguishable."""

    def __init__(self) -> None:
        super().__init__("Incorrect email or password")


class InvalidTokenError(AuthenticationError):
    """The access token is malformed, tampered with, or expired."""

    def __init__(self) -> None:
        super().__init__("Invalid or expired token")


class UserNotActiveError(AuthenticationError):
    """The token is genuine but its user no longer exists or has been deactivated."""

    def __init__(self) -> None:
        super().__init__("User is not active")
