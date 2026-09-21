"""Who is calling: the bearer token on the request, resolved to an active user.

This module is the seam the rest of the API builds on. A feature route asks for
``CurrentUserId`` and receives a ``uuid.UUID``; it never sees a JWT, a ``User`` or the users
table. Tests of such routes supply a user with
``app.dependency_overrides[get_current_user_id]`` (``tests/api/conftest.py``: ``sign_in``).

``StreamingUserId`` is the same seam for the one route whose work waits for the client: it
answers the same 401s, and differs only in where the caller is read.
"""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from app.api.dependencies import ContainerDep, GetCurrentUserDep
from app.api.session_policy import SESSION_COOKIE
from app.application.errors import AuthenticationError
from app.application.use_cases.get_current_user import GetCurrentUser
from app.domain.user import User

BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}

# Relative tokenUrl, so Swagger's Authorize button keeps working behind a path prefix.
# auto_error=False: the 401 for a missing token is raised below, with the same shape and
# challenge header as every other authentication failure.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


def request_credential(
    request: Request,
    container: ContainerDep,
    bearer: Annotated[str | None, Depends(oauth2_scheme)],
) -> str | None:
    # Explicit Authorization always wins, including an invalid scheme or token.
    if "authorization" in request.headers:
        return bearer
    token = request.cookies.get(SESSION_COOKIE)
    if token and request.method not in {"GET", "HEAD", "OPTIONS"}:
        container.browser_session.protect(request)
    return token


Credential = Annotated[str | None, Depends(request_credential)]


def unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail, headers=BEARER_CHALLENGE)


async def _resolve(use_case: GetCurrentUser, token: str | None) -> User | None:
    if token is None:
        return None
    try:
        return await use_case.execute(token)
    except AuthenticationError:
        return None


def _signed_in(token: str | None, user: User | None) -> User:
    if token is None:
        raise unauthorized("Not authenticated")
    if user is None:
        # One message for a bad token and for a vanished or deactivated user.
        raise unauthorized("Could not validate credentials")
    return user


async def _authenticate(
    token: Credential,
    use_case: GetCurrentUserDep,
) -> User | None:
    """The active user the token belongs to, or None. FastAPI caches it per request, so
    everything that asks who is calling resolves the caller once, in the one unit of work
    of the request."""
    return await _resolve(use_case, token)


async def _authenticate_apart(
    token: Credential,
    container: ContainerDep,
) -> User | None:
    """The same caller, read in a unit of work that ends here instead of the request's.

    For a route whose work waits for the client, such as the file upload: it must hold no
    database connection while the body arrives, and reading the caller through the
    request's unit of work would hold one for the whole route (ADR 0008).
    """
    if token is None:
        return None
    async with container.request_scope() as scope:
        return await _resolve(scope.get_current_user, token)


async def get_current_user(
    token: Credential,
    user: Annotated[User | None, Depends(_authenticate)],
) -> User:
    return _signed_in(token, user)


async def get_optional_user_id(
    user: Annotated[User | None, Depends(_authenticate)],
) -> uuid.UUID | None:
    """For a dependency that must not answer 401 itself: the rate limiter counts a caller
    it cannot identify by address instead, and leaves the 401 to the route."""
    return None if user is None else user.id


async def get_current_user_id(user: Annotated[User, Depends(get_current_user)]) -> uuid.UUID:
    return user.id


async def get_streaming_user_id(
    token: Credential,
    user: Annotated[User | None, Depends(_authenticate_apart)],
) -> uuid.UUID:
    """``get_current_user_id`` for a route that streams its body."""
    return _signed_in(token, user).id


async def get_optional_streaming_user_id(
    user: Annotated[User | None, Depends(_authenticate_apart)],
) -> uuid.UUID | None:
    """``get_optional_user_id`` for a route that streams its body."""
    return None if user is None else user.id


OptionalUser = Annotated[User | None, Depends(_authenticate)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentUserId = Annotated[uuid.UUID, Depends(get_current_user_id)]
OptionalUserId = Annotated[uuid.UUID | None, Depends(get_optional_user_id)]
StreamingUserId = Annotated[uuid.UUID, Depends(get_streaming_user_id)]
OptionalStreamingUserId = Annotated[uuid.UUID | None, Depends(get_optional_streaming_user_id)]
