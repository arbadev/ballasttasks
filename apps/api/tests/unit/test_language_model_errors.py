"""The failures a LanguageModel may raise: one family, no vendor in sight."""

import pytest

from app.application.ports.language_model import (
    LanguageModelAuthenticationError,
    LanguageModelError,
    LanguageModelInvalidResponseError,
    LanguageModelRateLimitedError,
    LanguageModelTimeoutError,
    LanguageModelUnavailableError,
)

FAILURES = [
    LanguageModelUnavailableError,
    LanguageModelRateLimitedError,
    LanguageModelAuthenticationError,
    LanguageModelInvalidResponseError,
    LanguageModelTimeoutError,
]


@pytest.mark.parametrize("failure", FAILURES)
def test_every_failure_is_a_language_model_error_that_names_the_provider(
    failure: type[LanguageModelError],
) -> None:
    error = failure("acme", "HTTP 418")

    assert isinstance(error, LanguageModelError)
    assert error.provider == "acme"
    assert "acme" in str(error)
    assert "HTTP 418" in str(error)


def test_the_failures_are_distinct_so_a_caller_can_tell_them_apart() -> None:
    for failure in FAILURES:
        others = [other for other in FAILURES if other is not failure]
        assert not [other for other in others if issubclass(failure, other)]
