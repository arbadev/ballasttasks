"""Request-time access to what the composition root built.

This module only READS from the container stored on the application; it never builds
an adapter. ``AppContainer`` states the little the HTTP layer needs, so the API does
not import the composition root or any infrastructure module.
"""

from typing import Annotated, Protocol, cast

from fastapi import Depends, Request

from app.application.ports.language_model import LanguageModel
from app.application.use_cases.authenticate_user import AuthenticateUser
from app.application.use_cases.check_readiness import CheckReadiness
from app.application.use_cases.get_current_user import GetCurrentUser
from app.application.use_cases.register_user import RegisterUser


class AppContainer(Protocol):
    @property
    def check_readiness(self) -> CheckReadiness: ...

    @property
    def language_model(self) -> LanguageModel: ...

    @property
    def register_user(self) -> RegisterUser: ...

    @property
    def authenticate_user(self) -> AuthenticateUser: ...

    @property
    def get_current_user(self) -> GetCurrentUser: ...


def get_container(request: Request) -> AppContainer:
    return cast(AppContainer, request.app.state.container)


ContainerDep = Annotated[AppContainer, Depends(get_container)]


def get_check_readiness(container: ContainerDep) -> CheckReadiness:
    return container.check_readiness


def get_language_model(container: ContainerDep) -> LanguageModel:
    return container.language_model


def get_register_user(container: ContainerDep) -> RegisterUser:
    return container.register_user


def get_authenticate_user(container: ContainerDep) -> AuthenticateUser:
    return container.authenticate_user


def get_get_current_user(container: ContainerDep) -> GetCurrentUser:
    return container.get_current_user


CheckReadinessDep = Annotated[CheckReadiness, Depends(get_check_readiness)]
LanguageModelDep = Annotated[LanguageModel, Depends(get_language_model)]
RegisterUserDep = Annotated[RegisterUser, Depends(get_register_user)]
AuthenticateUserDep = Annotated[AuthenticateUser, Depends(get_authenticate_user)]
GetCurrentUserDep = Annotated[GetCurrentUser, Depends(get_get_current_user)]
