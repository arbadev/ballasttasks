"""Hand-written test doubles for the application ports."""

import asyncio


class StubHealthCheck:
    def __init__(self, name: str, *, healthy: bool = True) -> None:
        self.name = name
        self._healthy = healthy

    async def check(self) -> bool:
        return self._healthy


class RaisingHealthCheck:
    def __init__(self, name: str) -> None:
        self.name = name

    async def check(self) -> bool:
        raise RuntimeError(f"{self.name} exploded")


class HangingHealthCheck:
    def __init__(self, name: str) -> None:
        self.name = name

    async def check(self) -> bool:
        await asyncio.sleep(60)
        return True
