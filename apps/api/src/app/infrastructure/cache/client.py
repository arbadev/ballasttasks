from redis.asyncio import Redis

DEFAULT_TIMEOUT_SECONDS = 5.0


def create_redis_client(url: str, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> Redis:
    """Async Redis client. Lazy: nothing connects until the first command."""
    client: Redis = Redis.from_url(
        url,
        socket_connect_timeout=timeout_seconds,
        socket_timeout=timeout_seconds,
        decode_responses=True,
    )
    return client
