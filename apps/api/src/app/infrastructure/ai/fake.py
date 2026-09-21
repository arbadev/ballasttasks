import json
from typing import ClassVar

from app.application.use_cases.generate_step_titles import PROMPT_PREFIX


class FakeLanguageModel:
    """Deterministic, offline LanguageModel. Explicit opt-in (never a fallback): needs no API key.

    It never fails, so it raises none of the port's ``LanguageModelError``s and its
    ``check`` is always True.
    """

    provider: ClassVar[str] = "fake"

    def __init__(self, *, model: str) -> None:
        self.model = model

    async def generate(self, prompt: str) -> str:
        if prompt.startswith(PROMPT_PREFIX):
            return json.dumps(["Clarify the goal", "Implement the task", "Verify the result"])
        return f"[{self.provider}:{self.model}] {prompt}"

    async def check(self) -> bool:
        return True
