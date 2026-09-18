from app.application.ports.language_model import LanguageModel


class LanguageModelHealthCheck:
    """Exposes any LanguageModel as a HealthCheck so readiness stays one uniform list."""

    name = "ai"

    def __init__(self, language_model: LanguageModel) -> None:
        self._language_model = language_model

    async def check(self) -> bool:
        try:
            return bool(await self._language_model.check())
        except Exception:
            return False
