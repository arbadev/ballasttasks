from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies import AuthenticateUserDep, RegisterUserDep
from app.api.schemas.auth import RegisterRequest, TokenResponse, UserResponse
from app.api.schemas.errors import ErrorResponse
from app.api.security import CurrentUser, unauthorized
from app.application.errors import EmailAlreadyRegisteredError, InvalidCredentialsError

router = APIRouter(prefix="/auth", tags=["auth"])

UNAUTHORIZED = {
    "model": ErrorResponse,
    "headers": {"WWW-Authenticate": {"schema": {"type": "string", "const": "Bearer"}}},
}


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=UserResponse,
    summary="Create a user account",
    responses={
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The email is already registered",
        }
    },
)
async def register(body: RegisterRequest, register_user: RegisterUserDep) -> UserResponse:
    try:
        user = await register_user.execute(
            email=body.email, full_name=body.full_name, password=body.password
        )
    except EmailAlreadyRegisteredError:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already registered") from None
    return UserResponse.from_user(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Exchange an email and password for an access token",
    description=(
        "OAuth2 password form (`application/x-www-form-urlencoded`): put the email in "
        "`username`. Every failure, whatever its cause, is the same 401."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            **UNAUTHORIZED,
            "description": "Incorrect email or password",
        }
    },
)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    authenticate_user: AuthenticateUserDep,
) -> TokenResponse:
    try:
        token = await authenticate_user.execute(email=form.username, password=form.password)
    except InvalidCredentialsError:
        raise unauthorized("Incorrect email or password") from None
    return TokenResponse(access_token=token)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="The user the bearer token belongs to",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            **UNAUTHORIZED,
            "description": "Missing, invalid or expired token, or the user is no longer active",
        }
    },
)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse.from_user(user)
