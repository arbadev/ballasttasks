"""Request-time access to what the composition root built.

This module only READS from the container stored on the application; it never builds
an adapter. ``AppContainer`` states the little the HTTP layer needs, so the API does
not import the composition root or any infrastructure module.
"""

from typing import Annotated, Protocol, cast

from fastapi import Depends, Request

from app.application.ports.language_model import LanguageModel
from app.application.use_cases.check_readiness import CheckReadiness


class AppContainer(Protocol):
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
