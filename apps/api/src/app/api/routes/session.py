"""Browser-only cookie endpoints; the OAuth2 bearer endpoints remain unchanged."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies import (
    AuthenticateUserDep,
    ContainerDep,
    GetCurrentUserDep,
    RedeemSsoCodeDep,
)
from app.api.rate_limit import TOO_MANY_REQUESTS, limit_auth_attempts, limit_requests
from app.api.schemas.auth import UserResponse
from app.api.schemas.errors import ErrorResponse
from app.api.schemas.sso import SsoExchangeRequest
from app.api.security import Credential, OptionalUser, unauthorized
from app.application.errors import InvalidCredentialsError, InvalidSsoCodeError


def protect_browser(request: Request, container: ContainerDep) -> None:
    container.browser_session.protect(request)


router = APIRouter(
    prefix="/auth/session",
    tags=["auth"],
    responses={**TOO_MANY_REQUESTS, 401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)


@router.post(
    "",
    response_model=UserResponse,
    dependencies=[Depends(limit_auth_attempts), Depends(protect_browser)],
)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    authenticate_user: AuthenticateUserDep,
    get_user: GetCurrentUserDep,
    container: ContainerDep,
    response: Response,
) -> UserResponse:
    try:
        token = await authenticate_user.execute(email=form.username, password=form.password)
    except InvalidCredentialsError:
        raise unauthorized("Incorrect email or password") from None
    user = await get_user.execute(token)
    container.browser_session.issue(response, token)
    return UserResponse.from_user(user)


@router.get("", response_model=UserResponse | None, dependencies=[Depends(limit_requests)])
async def restore(user: OptionalUser, token: Credential, response: Response) -> UserResponse | None:
    response.headers["Cache-Control"] = "no-store"
    if token is None:
        return None
    if user is None:
        raise unauthorized("Could not validate credentials")
    return UserResponse.from_user(user)


@router.delete(
    "", status_code=204, dependencies=[Depends(limit_requests), Depends(protect_browser)]
)
async def logout(container: ContainerDep, response: Response) -> None:
    # Idempotent even when expired. This removes the browser cookie, not other JWTs.
    container.browser_session.clear(response)


@router.post(
    "/sso",
    response_model=UserResponse,
    dependencies=[Depends(limit_auth_attempts), Depends(protect_browser)],
)
async def exchange(
    body: SsoExchangeRequest,
    redeem: RedeemSsoCodeDep,
    get_user: GetCurrentUserDep,
    container: ContainerDep,
    response: Response,
) -> UserResponse:
    try:
        token = await redeem.execute(body.code)
    except InvalidSsoCodeError:
        raise unauthorized("Invalid or expired code") from None
    user = await get_user.execute(token)
    container.browser_session.issue(response, token)
    return UserResponse.from_user(user)
