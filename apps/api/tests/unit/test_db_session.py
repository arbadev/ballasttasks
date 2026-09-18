from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.base import Base
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.session import create_session_factory
from tests.conftest import DOWN_DATABASE_URL


async def test_session_factory_is_bound_to_the_engine() -> None:
    engine = create_engine(DOWN_DATABASE_URL)

    async with create_session_factory(engine)() as session:
        assert isinstance(session, AsyncSession)
        assert session.bind is engine

    await engine.dispose()


def test_baseline_metadata_has_no_tables_yet() -> None:
    assert Base.metadata.tables == {}
