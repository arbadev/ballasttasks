from collections.abc import Sequence

from app.application.ports.people_directory import PeopleDirectory
from app.domain.user import Person


class ListPeople:
    """Who a task can be given to. A ``Person`` carries no email address."""

    def __init__(self, people: PeopleDirectory) -> None:
        self._people = people

    async def execute(self) -> Sequence[Person]:
        return await self._people.list_active()
