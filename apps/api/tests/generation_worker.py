"""Offline worker fixture: same composition and Celery registration as production.

Only the LanguageModel factory is replaced. No external provider is contacted.
"""

import asyncio
import json

from app.application.ports.language_model import LanguageModelUnavailableError
from app.bootstrap import build_worker, load_settings
from app.infrastructure.ai.fake import FakeLanguageModel
from app.infrastructure.ai.registry import AI_PROVIDERS


class ControlledLanguageModel(FakeLanguageModel):
    async def generate(self, prompt: str) -> str:
        data = json.loads(prompt.split("\nTASK_DATA\n")[1])
        title = data["title"]
        if title == "timeout":
            await asyncio.sleep(10)
        # Long enough to observe STARTED through a real HTTP poll.
        await asyncio.sleep(0.2)
        if title == "provider_error":
            raise LanguageModelUnavailableError("fake", "PRIVATE-PROVIDER-SECRET")
        if title == "empty":
            return "[]"
        if title == "malformed":
            return "__import__('os').system('never execute this')"
        if title == "oversized":
            return json.dumps(["x" * 201])
        if title == "too_many":
            return json.dumps(["step"] * 21)
        if title == "context":
            # Echo only the fields this test supplied, proving real-worker prompt inputs.
            return json.dumps([data["description"], *data["existing_steps"]])
        return await super().generate(prompt)


AI_PROVIDERS["fake"] = lambda ai, _client: ControlledLanguageModel(model=ai.model)
celery_app = build_worker(load_settings())
