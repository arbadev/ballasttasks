from typing import Protocol


class LanguageModel(Protocol):
    """Text generation backed by some AI provider."""

    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def generate(self, prompt: str) -> str:
        """Return the (non-empty) completion for ``prompt``."""
        ...

    async def check(self) -> bool:
        """Return True when the provider is reachable and usable."""
        ...
