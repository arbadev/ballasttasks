"""One transaction per unit of work, committed or rolled back in exactly one place.

How the pieces fit (the mechanism every repository shares):

1. ``transactional_session`` opens an ``AsyncSession`` from the container's
   ``session_factory``, commits when the block ends normally, rolls back when it raises,
   and always closes the session.
2. Repositories receive that session and never commit, so everything done through the
   repositories of one scope succeeds or fails together.
3. The composition root (``app.bootstrap``) wraps it as ``Container.request_scope``: it
   builds the repositories around ONE session and hands them to the use cases. A new
   repository is one more field there; nothing here changes.
4. The HTTP layer enters that scope once per request (``app.api.dependencies``) and ends
   it before the response is sent, so a failed commit is an error response, never a
   success the client already saw.

Outside HTTP (a Celery job, a script) the same ``container.request_scope()`` is the unit
of work.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@asynccontextmanager
async def transactional_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory.begin() as session:
        yield session
