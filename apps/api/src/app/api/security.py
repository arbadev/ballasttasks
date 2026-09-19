"""Who is calling: the bearer token on the request, resolved to an active user.

This module is the seam the rest of the API builds on. A feature route asks for
``CurrentUserId`` and receives a ``uuid.UUID``; it never sees a JWT, a ``User`` or the users
table. Tests of such routes supply a user with
``app.dependency_overrides[get_current_user_id]``.
"""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.api.dependencies import GetCurrentUserDep
from app.application.errors import AuthenticationError
from app.domain.user import User

BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}

# Relative tokenUrl, so Swagger's Authorize button keeps working behind a path prefix.
# auto_error=False: the 401 for a missing token is raised below, with the same shape and
# challenge header as every other authentication failure.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


def unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail, headers=BEARER_CHALLENGE)


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    use_case: GetCurrentUserDep,
) -> User:
    if token is None:
        raise unauthorized("Not authenticated")
    try:
        return await use_case.execute(token)
    except AuthenticationError:
        # One message for a bad token and for a vanished or deactivated user.
        raise unauthorized("Could not validate credentials") from None


async def get_current_user_id(user: Annotated[User, Depends(get_current_user)]) -> uuid.UUID:
    return user.id


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentUserId = Annotated[uuid.UUID, Depends(get_current_user_id)]
