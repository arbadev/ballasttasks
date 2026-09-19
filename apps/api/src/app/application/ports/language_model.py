from typing import Protocol


class LanguageModelError(Exception):
    """``generate`` failed. The subclass says why, in terms no vendor owns.

    ``reason`` is written by the adapter (an HTTP status, "empty completion"); it never
    holds a credential or a provider's response body.
    """

    def __init__(self, provider: str, reason: str) -> None:
        super().__init__(f"{provider}: {reason}")
        self.provider = provider


class LanguageModelUnavailableError(LanguageModelError):
    """The provider cannot serve requests right now: unreachable, failing, or out of credit."""


class LanguageModelRateLimitedError(LanguageModelError):
    """The provider is throttling this caller; the same request may succeed later."""


class LanguageModelAuthenticationError(LanguageModelError):
    """The provider rejected the configured credentials or denies them this model."""


class LanguageModelInvalidResponseError(LanguageModelError):
    """The provider answered, but not with a usable completion: a malformed or empty body,
    a blocked prompt, or a rejection with no better category (such as an unknown model)."""


class LanguageModelTimeoutError(LanguageModelError):
    """No answer arrived within the configured time."""


class LanguageModel(Protocol):
    """Text generation backed by some AI provider."""

    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def generate(self, prompt: str) -> str:
        """Return the (non-empty) completion for ``prompt``.

        Every failure is a ``LanguageModelError`` subclass; nothing vendor-specific escapes.
        """
        ...

    async def check(self) -> bool:
        """Return True when the provider is reachable and accepts the credentials.

        Never raises and never generates: readiness is polled, so it must cost nothing.
        """
        ...
