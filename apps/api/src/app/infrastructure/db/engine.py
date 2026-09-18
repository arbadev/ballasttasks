from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

DEFAULT_CONNECT_TIMEOUT_SECONDS = 5


def create_engine(
    url: str,
    *,
    echo: bool = False,
    connect_timeout_seconds: int = DEFAULT_CONNECT_TIMEOUT_SECONDS,
) -> AsyncEngine:
    """Async PostgreSQL engine (psycopg). Lazy: nothing connects until first use."""
    return create_async_engine(
        url,
        echo=echo,
        pool_pre_ping=True,
        connect_args={"connect_timeout": connect_timeout_seconds},
    )
