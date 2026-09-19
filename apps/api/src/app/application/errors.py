"""Errors the application layer raises; the presentation layer maps them to HTTP."""

import uuid

from app.domain.task_key import TaskKey


class TaskNotFound(LookupError):  # noqa: N818 - named for what happened, as the API reports it
    """No task has that id, or that key."""

    def __init__(self, reference: uuid.UUID | TaskKey) -> None:
        super().__init__(f"Task {reference} not found")
        self.reference = reference

    @property
    def task_id(self) -> uuid.UUID | None:
        return self.reference if isinstance(self.reference, uuid.UUID) else None


class InvalidTaskReferenceError(ValueError):
    """The text is neither a task id nor a task key such as ``BT-04``."""

    def __init__(self, text: str) -> None:
        super().__init__("must be a task id (UUID) or a task key such as BT-04")
        self.text = text


class StoredTaskInvalid(RuntimeError):  # noqa: N818 - named for what happened
    """A stored task breaks a domain rule: a server fault, never the caller's request."""

    def __init__(self, task_id: uuid.UUID) -> None:
        super().__init__(f"Stored task {task_id} is invalid")
        self.task_id = task_id


class AttachmentNotFound(LookupError):  # noqa: N818 - named for what happened, as the API reports it
    """No attachment has that id, or it belongs to another task than the one named."""

    def __init__(self, attachment_id: uuid.UUID) -> None:
        super().__init__(f"Attachment {attachment_id} not found")
        self.attachment_id = attachment_id


class FileTooLargeError(ValueError):
    def __init__(self, max_bytes: int) -> None:
        super().__init__(f"File exceeds {max_bytes} bytes")
        self.max_bytes = max_bytes


class EmptyFileError(ValueError):
    def __init__(self) -> None:
        super().__init__("File must not be empty")


class UnsupportedFileTypeError(ValueError):
    def __init__(self) -> None:
        super().__init__("File must have PDF, PNG, JPEG, GIF or WebP leading bytes")


class AttachmentHasNoContent(LookupError):  # noqa: N818
    def __init__(self) -> None:
        super().__init__("Links have no stored content")


class AttachmentContentMissing(AttachmentNotFound):
    pass


class StoredAttachmentInvalid(RuntimeError):  # noqa: N818 - named for what happened
    """A stored attachment breaks a domain rule: a server fault, never the caller's request."""

    def __init__(self, attachment_id: uuid.UUID) -> None:
        super().__init__(f"Stored attachment {attachment_id} is invalid")
        self.attachment_id = attachment_id


class StepNotFound(LookupError):  # noqa: N818 - named for what happened, as the API reports it
    """The task has no step with that id (a step of another task is not found either)."""

    def __init__(self, step_id: uuid.UUID) -> None:
        super().__init__(f"Step {step_id} not found")
        self.step_id = step_id


class InvalidAssigneeError(Exception):
    """The assignee is not a user who can be given a task: unknown, or no longer active.

    One error and one message for both, from the ``UserDirectory`` check and from the
    repository when the store itself refuses the assignee.
    """

    def __init__(self, assignee_id: uuid.UUID) -> None:
        super().__init__("assignee_id must be the id of an active user")
        self.assignee_id = assignee_id


class ProjectNotFound(LookupError):  # noqa: N818 - named for what happened, as the API reports it
    def __init__(self, project_id: uuid.UUID) -> None:
        super().__init__(f"Project {project_id} not found")
        self.project_id = project_id


class UnknownProjectError(Exception):
    """A task names a project that is not stored: the caller's mistake, like a bad assignee.

    One error from the use case's check and from the repository when the store itself
    refuses the project, so a project that vanishes in between is still the caller's ``422``.
    """

    def __init__(self, project_id: uuid.UUID) -> None:
        super().__init__("project_id must be the id of an existing project")
        self.project_id = project_id


class ProjectKeyTakenError(Exception):
    """Another project already has this key."""

    def __init__(self, key: str) -> None:
        super().__init__(f"Project key {key!r} is already taken")
        self.key = key


class UserNotFound(LookupError):  # noqa: N818 - named for what happened
    def __init__(self, user_id: uuid.UUID) -> None:
        super().__init__(f"User {user_id} not found")
        self.user_id = user_id


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


class InvalidSsoCodeError(AuthenticationError):
    """The one-time exchange code is unknown, already used or expired, or its user is gone."""

    def __init__(self) -> None:
        super().__init__("Invalid or expired code")


class SsoError(Exception):
    """A single sign-on attempt failed. Messages are constant: they never repeat a state, a
    code, a nonce, a token or an email, so they are safe to log and to show."""


class UnknownIdentityProviderError(SsoError):
    """No such provider is enabled: unknown and disabled are deliberately one answer."""

    def __init__(self) -> None:
        super().__init__("Unknown single sign-on provider")


class SsoStateInvalidError(SsoError):
    """The callback does not belong to a sign-in this browser started: the state is unknown,
    already used, expired, issued for another provider or bound to another browser."""

    def __init__(self) -> None:
        super().__init__("The sign-in state is not valid")


class IdentityCodeRejectedError(SsoError):
    """The provider did not vouch for this sign-in: it refused the authorization code, or
    what it returned failed verification (signature, issuer, audience, expiry, nonce)."""

    def __init__(self) -> None:
        super().__init__("The identity provider rejected the sign-in")


class IdentityProviderUnavailableError(SsoError):
    """The provider could not be reached, did not answer as its protocol says, or refused
    this application's own credentials: nothing the person signing in did, or can fix."""

    def __init__(self) -> None:
        super().__init__("The identity provider is unavailable")


class EmailNotVerifiedError(SsoError):
    """The provider has not verified the email address, so it proves nothing about who
    owns it: no sign-in, and above all no link to an existing user."""

    def __init__(self) -> None:
        super().__init__("The identity provider has not verified this email address")


class SsoSignInRefusedError(SsoError):
    """The identity is genuine but must not be given this account: the user with that email
    is already linked to a different subject of the same provider."""

    def __init__(self) -> None:
        super().__init__("This identity cannot be linked to the account with its email")


class IdentityAlreadyLinkedError(Exception):
    """The store refused a link: that (provider, subject) already belongs to a user, or the
    user already has an identity at that provider."""

    def __init__(self) -> None:
        super().__init__("Identity already linked")
