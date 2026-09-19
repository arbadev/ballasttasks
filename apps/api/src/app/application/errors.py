"""Errors the application layer raises; the presentation layer maps them to HTTP."""

import uuid


class TaskNotFound(LookupError):  # noqa: N818 - named for what happened, as the API reports it
    def __init__(self, task_id: uuid.UUID) -> None:
        super().__init__(f"Task {task_id} not found")
        self.task_id = task_id


class StoredTaskInvalid(RuntimeError):  # noqa: N818 - named for what happened
    """A stored task breaks a domain rule: a server fault, never the caller's request."""

    def __init__(self, task_id: uuid.UUID) -> None:
        super().__init__(f"Stored task {task_id} is invalid")
        self.task_id = task_id


class InvalidAssigneeError(Exception):
    """The assignee is not a user who can be given a task: unknown, or no longer active.

    One error and one message for both, from the ``UserDirectory`` check and from the
    repository when the store itself refuses the assignee.
    """

    def __init__(self, assignee_id: uuid.UUID) -> None:
        super().__init__("assignee_id must be the id of an active user")
        self.assignee_id = assignee_id


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
