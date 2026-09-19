"""The people list: who a task can be given to."""

from fastapi import APIRouter, Depends, status

from app.api.dependencies import ListPeopleDep
from app.api.schemas.errors import ErrorResponse
from app.api.schemas.users import PeopleResponse, PersonResponse
from app.api.security import get_current_user_id

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(get_current_user_id)],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "Not authenticated"}
    },
)


@router.get(
    "",
    summary="List the active users, by name, for the assignee picker",
    description=(
        "Id, full name, initials and role label only. No email address of another user is "
        "ever exposed; a user reads their own through `GET /auth/me`."
    ),
    response_model=PeopleResponse,
)
async def list_people(list_people: ListPeopleDep) -> PeopleResponse:
    people = await list_people.execute()
    return PeopleResponse(items=[PersonResponse.of(person) for person in people])
