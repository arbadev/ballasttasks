"""Request-time access to what the composition root built.

This module only READS from the container stored on the application; it never builds
an adapter. ``AppContainer`` states the little the HTTP layer needs, so the API does
not import the composition root or any infrastructure module.
"""

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from typing import Annotated, Protocol, cast

from fastapi import Depends, Request

from app.application.ports.identity_provider import IdentityProvider
from app.application.ports.language_model import LanguageModel
from app.application.ports.rate_limiter import RateLimiter, RateLimitPolicy
from app.application.sso import SsoConfig
from app.application.use_cases.add_step import AddStep
from app.application.use_cases.add_steps import AddSteps
from app.application.use_cases.assess_attention import AssessAttention
from app.application.use_cases.attach_file import AttachFile
from app.application.use_cases.attach_link import AttachLink
from app.application.use_cases.authenticate_user import AuthenticateUser
from app.application.use_cases.check_readiness import CheckReadiness
from app.application.use_cases.complete_sso_sign_in import CompleteSsoSignIn
from app.application.use_cases.create_project import CreateProject
from app.application.use_cases.create_task import CreateTask
from app.application.use_cases.delete_step import DeleteStep
from app.application.use_cases.delete_task import DeleteTask
from app.application.use_cases.get_current_user import GetCurrentUser
from app.application.use_cases.get_project import GetProject
from app.application.use_cases.get_task import GetTask
from app.application.use_cases.list_activity import ListActivity
from app.application.use_cases.list_attachments import ListAttachments
from app.application.use_cases.list_people import ListPeople
from app.application.use_cases.list_projects import ListProjects
from app.application.use_cases.list_steps import ListSteps
from app.application.use_cases.list_tasks import ListTasks
from app.application.use_cases.open_attachment_content import OpenAttachmentContent
from app.application.use_cases.post_comment import PostComment
from app.application.use_cases.redeem_sso_code import RedeemSsoCode
from app.application.use_cases.register_user import RegisterUser
from app.application.use_cases.remove_attachment import RemoveAttachment
from app.application.use_cases.reorder_steps import ReorderSteps
from app.application.use_cases.start_sso_sign_in import StartSsoSignIn
from app.application.use_cases.summarise_tasks import SummariseTasks
from app.application.use_cases.tally_tasks import TallyTasks
from app.application.use_cases.update_profile import UpdateProfile
from app.application.use_cases.update_project import UpdateProject
from app.application.use_cases.update_step import UpdateStep
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

    @property
    def complete_sso_sign_in(self) -> CompleteSsoSignIn: ...

    @property
    def redeem_sso_code(self) -> RedeemSsoCode: ...

    @property
    def summarise_tasks(self) -> SummariseTasks: ...

    @property
    def assess_attention(self) -> AssessAttention: ...

    @property
    def create_project(self) -> CreateProject: ...

    @property
    def get_project(self) -> GetProject: ...

    @property
    def list_projects(self) -> ListProjects: ...

    @property
    def update_project(self) -> UpdateProject: ...

    @property
    def list_people(self) -> ListPeople: ...

    @property
    def update_profile(self) -> UpdateProfile: ...

    @property
    def attach_link(self) -> AttachLink: ...

    @property
    def list_attachments(self) -> ListAttachments: ...

    @property
    def remove_attachment(self) -> RemoveAttachment: ...

    @property
    def open_attachment_content(self) -> OpenAttachmentContent: ...

    @property
    def tally_tasks(self) -> TallyTasks: ...

    @property
    def list_steps(self) -> ListSteps: ...

    @property
    def add_step(self) -> AddStep: ...

    @property
    def add_steps(self) -> AddSteps: ...

    @property
    def update_step(self) -> UpdateStep: ...

    @property
    def reorder_steps(self) -> ReorderSteps: ...

    @property
    def delete_step(self) -> DeleteStep: ...

    @property
    def post_comment(self) -> PostComment: ...

    @property
    def list_activity(self) -> ListActivity: ...


class RateLimiting(Protocol):
    """The limiter and the rules it is applied with (``api/rate_limit.py``)."""

    @property
    def limiter(self) -> RateLimiter: ...

    @property
    def enabled(self) -> bool: ...

    @property
    def trust_proxy(self) -> bool: ...

    @property
    def auth(self) -> RateLimitPolicy: ...

    @property
    def authenticated(self) -> RateLimitPolicy: ...

    @property
    def anonymous(self) -> RateLimitPolicy: ...


class AppContainer(Protocol):
    @property
    def request_scope(self) -> Callable[[], AbstractAsyncContextManager[RequestScope]]: ...

    @property
    def check_readiness(self) -> CheckReadiness: ...

    @property
    def language_model(self) -> LanguageModel: ...

    @property
    def identity_providers(self) -> Mapping[str, IdentityProvider]: ...

    @property
    def start_sso_sign_in(self) -> StartSsoSignIn: ...

    @property
    def sso(self) -> SsoConfig: ...

    @property
    def rate_limiting(self) -> RateLimiting: ...

    # Not on a request scope: it opens the short units of work an upload needs itself, so
    # the body streams with no database connection held.
    @property
    def attach_file(self) -> AttachFile: ...


def get_container(request: Request) -> AppContainer:
    return cast(AppContainer, request.app.state.container)


ContainerDep = Annotated[AppContainer, Depends(get_container)]


def get_check_readiness(container: ContainerDep) -> CheckReadiness:
    return container.check_readiness


def get_language_model(container: ContainerDep) -> LanguageModel:
    return container.language_model


def get_identity_providers(container: ContainerDep) -> Mapping[str, IdentityProvider]:
    return container.identity_providers


def get_start_sso_sign_in(container: ContainerDep) -> StartSsoSignIn:
    return container.start_sso_sign_in


def get_sso_config(container: ContainerDep) -> SsoConfig:
    return container.sso


def get_rate_limiting(container: ContainerDep) -> RateLimiting:
    return container.rate_limiting


CheckReadinessDep = Annotated[CheckReadiness, Depends(get_check_readiness)]
LanguageModelDep = Annotated[LanguageModel, Depends(get_language_model)]
IdentityProvidersDep = Annotated[Mapping[str, IdentityProvider], Depends(get_identity_providers)]
StartSsoSignInDep = Annotated[StartSsoSignIn, Depends(get_start_sso_sign_in)]
SsoConfigDep = Annotated[SsoConfig, Depends(get_sso_config)]
RateLimitingDep = Annotated[RateLimiting, Depends(get_rate_limiting)]


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


def get_complete_sso_sign_in(scope: RequestScopeDep) -> CompleteSsoSignIn:
    return scope.complete_sso_sign_in


def get_redeem_sso_code(scope: RequestScopeDep) -> RedeemSsoCode:
    return scope.redeem_sso_code


CreateTaskDep = Annotated[CreateTask, Depends(get_create_task)]
GetTaskDep = Annotated[GetTask, Depends(get_get_task)]
ListTasksDep = Annotated[ListTasks, Depends(get_list_tasks)]
UpdateTaskDep = Annotated[UpdateTask, Depends(get_update_task)]
DeleteTaskDep = Annotated[DeleteTask, Depends(get_delete_task)]
RegisterUserDep = Annotated[RegisterUser, Depends(get_register_user)]
AuthenticateUserDep = Annotated[AuthenticateUser, Depends(get_authenticate_user)]
GetCurrentUserDep = Annotated[GetCurrentUser, Depends(get_get_current_user)]
CompleteSsoSignInDep = Annotated[CompleteSsoSignIn, Depends(get_complete_sso_sign_in)]
RedeemSsoCodeDep = Annotated[RedeemSsoCode, Depends(get_redeem_sso_code)]


def get_summarise_tasks(scope: RequestScopeDep) -> SummariseTasks:
    return scope.summarise_tasks


def get_assess_attention(scope: RequestScopeDep) -> AssessAttention:
    return scope.assess_attention


def get_create_project(scope: RequestScopeDep) -> CreateProject:
    return scope.create_project


def get_get_project(scope: RequestScopeDep) -> GetProject:
    return scope.get_project


def get_list_projects(scope: RequestScopeDep) -> ListProjects:
    return scope.list_projects


def get_update_project(scope: RequestScopeDep) -> UpdateProject:
    return scope.update_project


def get_list_people(scope: RequestScopeDep) -> ListPeople:
    return scope.list_people


def get_update_profile(scope: RequestScopeDep) -> UpdateProfile:
    return scope.update_profile


SummariseTasksDep = Annotated[SummariseTasks, Depends(get_summarise_tasks)]
AssessAttentionDep = Annotated[AssessAttention, Depends(get_assess_attention)]
CreateProjectDep = Annotated[CreateProject, Depends(get_create_project)]
GetProjectDep = Annotated[GetProject, Depends(get_get_project)]
ListProjectsDep = Annotated[ListProjects, Depends(get_list_projects)]
UpdateProjectDep = Annotated[UpdateProject, Depends(get_update_project)]
ListPeopleDep = Annotated[ListPeople, Depends(get_list_people)]
UpdateProfileDep = Annotated[UpdateProfile, Depends(get_update_profile)]


def get_attach_link(scope: RequestScopeDep) -> AttachLink:
    return scope.attach_link


def get_list_attachments(scope: RequestScopeDep) -> ListAttachments:
    return scope.list_attachments


def get_remove_attachment(scope: RequestScopeDep) -> RemoveAttachment:
    return scope.remove_attachment


def get_attach_file(container: ContainerDep) -> AttachFile:
    return container.attach_file


def get_open_attachment_content(scope: RequestScopeDep) -> OpenAttachmentContent:
    return scope.open_attachment_content


AttachFileDep = Annotated[AttachFile, Depends(get_attach_file)]
OpenAttachmentContentDep = Annotated[OpenAttachmentContent, Depends(get_open_attachment_content)]
AttachLinkDep = Annotated[AttachLink, Depends(get_attach_link)]
ListAttachmentsDep = Annotated[ListAttachments, Depends(get_list_attachments)]
RemoveAttachmentDep = Annotated[RemoveAttachment, Depends(get_remove_attachment)]


def get_tally_tasks(scope: RequestScopeDep) -> TallyTasks:
    return scope.tally_tasks


def get_list_steps(scope: RequestScopeDep) -> ListSteps:
    return scope.list_steps


def get_add_step(scope: RequestScopeDep) -> AddStep:
    return scope.add_step


def get_add_steps(scope: RequestScopeDep) -> AddSteps:
    return scope.add_steps


def get_update_step(scope: RequestScopeDep) -> UpdateStep:
    return scope.update_step


def get_reorder_steps(scope: RequestScopeDep) -> ReorderSteps:
    return scope.reorder_steps


def get_delete_step(scope: RequestScopeDep) -> DeleteStep:
    return scope.delete_step


def get_post_comment(scope: RequestScopeDep) -> PostComment:
    return scope.post_comment


def get_list_activity(scope: RequestScopeDep) -> ListActivity:
    return scope.list_activity


TallyTasksDep = Annotated[TallyTasks, Depends(get_tally_tasks)]
ListStepsDep = Annotated[ListSteps, Depends(get_list_steps)]
AddStepDep = Annotated[AddStep, Depends(get_add_step)]
AddStepsDep = Annotated[AddSteps, Depends(get_add_steps)]
UpdateStepDep = Annotated[UpdateStep, Depends(get_update_step)]
ReorderStepsDep = Annotated[ReorderSteps, Depends(get_reorder_steps)]
DeleteStepDep = Annotated[DeleteStep, Depends(get_delete_step)]
PostCommentDep = Annotated[PostComment, Depends(get_post_comment)]
ListActivityDep = Annotated[ListActivity, Depends(get_list_activity)]
