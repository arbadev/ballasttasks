import pytest

from app.application.use_cases.list_people import ListPeople
from app.application.use_cases.update_profile import ProfileChanges, UpdateProfile
from app.domain.user import InvalidProfileError, Person
from tests.auth_fakes import InMemoryUserDirectory, InMemoryUserRepository, a_user


@pytest.fixture
def users() -> InMemoryUserRepository:
    return InMemoryUserRepository()


async def test_people_are_the_active_users_by_name_without_their_emails(
    users: InMemoryUserRepository,
) -> None:
    tomas = a_user(full_name="Tomas Rey", role_label="frontend")
    andres = a_user(full_name="andres barradas", role_label="owner")
    gone = a_user(full_name="Lucia Marin", is_active=False)
    for user in (tomas, andres, gone):
        await users.add(user)

    people = await ListPeople(InMemoryUserDirectory(users)).execute()

    assert list(people) == [Person.of(andres), Person.of(tomas)]
    assert [person.initials for person in people] == ["AB", "TR"]
    assert not hasattr(people[0], "email")


async def test_update_profile_changes_only_the_given_fields(
    users: InMemoryUserRepository,
) -> None:
    user = a_user(full_name="Ada Lovelace")
    await users.add(user)
    update = UpdateProfile(users)

    labelled = await update.execute(user, ProfileChanges(role_label="backend"))
    renamed = await update.execute(labelled, ProfileChanges(full_name="Ada King"))
    cleared = await update.execute(renamed, ProfileChanges(role_label=None))

    assert (labelled.full_name, labelled.role_label) == ("Ada Lovelace", "backend")
    assert (renamed.full_name, renamed.role_label) == ("Ada King", "backend")
    assert (cleared.full_name, cleared.role_label) == ("Ada King", None)
    assert await users.get_by_id(user.id) == cleared
    assert (cleared.email, cleared.hashed_password) == (user.email, user.hashed_password)


async def test_update_profile_with_no_changes_returns_the_user_as_it_is(
    users: InMemoryUserRepository,
) -> None:
    user = a_user()
    await users.add(user)

    assert await UpdateProfile(users).execute(user, ProfileChanges()) is user


async def test_update_profile_rejects_a_blank_name_and_stores_nothing(
    users: InMemoryUserRepository,
) -> None:
    user = a_user()
    await users.add(user)

    with pytest.raises(InvalidProfileError):
        await UpdateProfile(users).execute(
            user, ProfileChanges(role_label="backend", full_name="  ")
        )

    assert await users.get_by_id(user.id) == user
