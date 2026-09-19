"""Contract every PeopleDirectory adapter must honour (Liskov).

The people list is its own port, not one more method on ``UserDirectory``: the task use cases
need a yes or a no about one id, the assignee picker needs names, and neither should have to
carry the other. The in-memory fake runs everywhere; the SQLAlchemy adapter runs the same
cases under the ``integration`` marker, in a database nothing is ever committed to.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.people_directory import PeopleDirectory
from app.application.ports.user_repository import UserRepository
from app.domain.user import Person
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.repositories.user import SqlAlchemyUserRepository
from app.infrastructure.db.repositories.user_directory import SqlAlchemyUserDirectory
from tests.auth_fakes import InMemoryUserDirectory, InMemoryUserRepository, a_user

ADAPTERS = [
    pytest.param("in-memory"),
    pytest.param("sqlalchemy-postgresql", marks=pytest.mark.integration),
]


@dataclass(frozen=True, slots=True)
class Store:
    users: UserRepository
    directory: PeopleDirectory


@pytest.fixture(params=ADAPTERS)
async def store(request: pytest.FixtureRequest) -> AsyncIterator[Store]:
    if request.param == "in-memory":
        users = InMemoryUserRepository()
        yield Store(users, InMemoryUserDirectory(users))
        return

    engine = create_engine(request.getfixturevalue("pristine_database_url"))
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            yield Store(SqlAlchemyUserRepository(session), SqlAlchemyUserDirectory(session))
        await transaction.rollback()
    await engine.dispose()


async def test_nobody_is_listed_when_there_are_no_users(store: Store) -> None:
    assert list(await store.directory.list_active()) == []


async def test_active_users_are_listed_by_name_whatever_the_case(store: Store) -> None:
    tomas = a_user(full_name="Tomas Rey", role_label="frontend")
    andres = a_user(full_name="andres barradas", role_label="owner")
    lucia = a_user(full_name="Lucia Marin")
    gone = a_user(full_name="Grace Hopper", is_active=False)
    for user in (tomas, andres, lucia, gone):
        await store.users.add(user)

    people = await store.directory.list_active()

    assert list(people) == [Person.of(andres), Person.of(lucia), Person.of(tomas)]


async def test_people_with_the_same_name_are_listed_in_a_stable_order(store: Store) -> None:
    twins = [a_user(full_name="Ada Lovelace") for _ in range(4)]
    for user in twins:
        await store.users.add(user)

    people = await store.directory.list_active()

    assert [person.id for person in people] == sorted(user.id for user in twins)
