from sqlalchemy.ext.asyncio import AsyncSession

import app.infrastructure.db.models  # noqa: F401  (registers every model on Base.metadata)
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


def test_importing_the_models_package_registers_the_tables_alembic_targets() -> None:
    assert set(Base.metadata.tables) >= {"users"}


async def test_sql_echo_never_logs_bound_parameters() -> None:
    """APP__DEBUG turns SQL echo on; the INSERT into users binds the password hash."""
    engine = create_engine(DOWN_DATABASE_URL, echo=True)

    assert engine.sync_engine.hide_parameters is True

    await engine.dispose()
