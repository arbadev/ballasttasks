from redis.asyncio import Redis


class RedisHealthCheck:
    name = "redis"

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def check(self) -> bool:
        try:
            return bool(await self._client.ping())
        except Exception:
            return False
