from datetime import timedelta

from redis.asyncio import Redis


class RedisOneTimeStore:
    """OneTimeStore on Redis: ``SET ... PX`` to keep, ``GETDEL`` to take.

    ``GETDEL`` (Redis 6.2+) reads and deletes in one command, so of concurrent takers
    exactly one gets the value, and Redis expires what nobody takes.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def put(self, key: str, value: str, *, ttl: timedelta) -> None:
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        await self._redis.set(key, value, px=ttl)

    async def take(self, key: str) -> str | None:
        value = await self._redis.getdel(key)
        if isinstance(value, bytes):  # a client built without decode_responses
            return value.decode()
        return None if value is None else str(value)
