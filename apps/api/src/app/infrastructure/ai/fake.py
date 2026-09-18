from typing import ClassVar


class FakeLanguageModel:
    """Deterministic, offline LanguageModel. The default provider: needs no API key."""

    provider: ClassVar[str] = "fake"

    def __init__(self, *, model: str) -> None:
        self.model = model

    async def generate(self, prompt: str) -> str:
        return f"[{self.provider}:{self.model}] {prompt}"

    async def check(self) -> bool:
        return True
