"""Request-time access to what the composition root built.

This module only READS from the container stored on the application; it never builds
an adapter. ``AppContainer`` states the little the HTTP layer needs, so the API does
not import the composition root or any infrastructure module.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated, Protocol, cast

from fastapi import Depends, Request

from app.application.ports.language_model import LanguageModel
from app.application.use_cases.authenticate_user import AuthenticateUser
from app.application.use_cases.check_readiness import CheckReadiness
from app.application.use_cases.create_task import CreateTask
from app.application.use_cases.delete_task import DeleteTask
from app.application.use_cases.get_current_user import GetCurrentUser
from app.application.use_cases.get_task import GetTask
from app.application.use_cases.list_tasks import ListTasks
from app.application.use_cases.register_user import RegisterUser
from app.application.use_cases.update_task import UpdateTask


class RequestScope(Protocol):
    """The use cases of one unit of work: they share one transaction."""

    @property
    def create_task(self) -> CreateTask: ...

    @property
    def get_task(self) -> GetTask: ...

    @property
    def list_tasks(self) -> ListTasks: ...

    @property
    def update_task(self) -> UpdateTask: ...

    @property
    def delete_task(self) -> DeleteTask: ...

    @property
    def register_user(self) -> RegisterUser: ...

    @property
    def authenticate_user(self) -> AuthenticateUser: ...

    @property
    def get_current_user(self) -> GetCurrentUser: ...


class AppContainer(Protocol):
    @property
    def request_scope(self) -> Callable[[], AbstractAsyncContextManager[RequestScope]]: ...

    @property
    def check_readiness(self) -> CheckReadiness: ...

    @property
    def language_model(self) -> LanguageModel: ...


def get_container(request: Request) -> AppContainer:
    return cast(AppContainer, request.app.state.container)


ContainerDep = Annotated[AppContainer, Depends(get_container)]


def get_check_readiness(container: ContainerDep) -> CheckReadiness:
    return container.check_readiness


def get_language_model(container: ContainerDep) -> LanguageModel:
    return container.language_model


CheckReadinessDep = Annotated[CheckReadiness, Depends(get_check_readiness)]
LanguageModelDep = Annotated[LanguageModel, Depends(get_language_model)]


async def get_request_scope(container: ContainerDep) -> AsyncIterator[RequestScope]:
    """One unit of work per request: committed when the route returns, rolled back when it
    raises. Every dependency of a request shares it (FastAPI caches it per request)."""
    async with container.request_scope() as scope:
        yield scope


# scope="function": the unit of work ends BEFORE the response is sent, so a commit that
# fails becomes an error response instead of following a success the client already saw.
RequestScopeDep = Annotated[RequestScope, Depends(get_request_scope, scope="function")]


def get_create_task(scope: RequestScopeDep) -> CreateTask:
    return scope.create_task


def get_get_task(scope: RequestScopeDep) -> GetTask:
    return scope.get_task


def get_list_tasks(scope: RequestScopeDep) -> ListTasks:
    return scope.list_tasks


def get_update_task(scope: RequestScopeDep) -> UpdateTask:
    return scope.update_task


def get_delete_task(scope: RequestScopeDep) -> DeleteTask:
    return scope.delete_task


def get_register_user(scope: RequestScopeDep) -> RegisterUser:
    return scope.register_user


def get_authenticate_user(scope: RequestScopeDep) -> AuthenticateUser:
    return scope.authenticate_user


def get_get_current_user(scope: RequestScopeDep) -> GetCurrentUser:
    return scope.get_current_user


CreateTaskDep = Annotated[CreateTask, Depends(get_create_task)]
GetTaskDep = Annotated[GetTask, Depends(get_get_task)]
ListTasksDep = Annotated[ListTasks, Depends(get_list_tasks)]
UpdateTaskDep = Annotated[UpdateTask, Depends(get_update_task)]
DeleteTaskDep = Annotated[DeleteTask, Depends(get_delete_task)]
RegisterUserDep = Annotated[RegisterUser, Depends(get_register_user)]
AuthenticateUserDep = Annotated[AuthenticateUser, Depends(get_authenticate_user)]
GetCurrentUserDep = Annotated[GetCurrentUser, Depends(get_get_current_user)]
