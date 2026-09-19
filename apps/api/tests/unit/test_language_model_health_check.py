"""LanguageModelHealthCheck's cache: ``GET /health/ready`` is public, so however often it
is hit, the provider (a keyed outbound call) is asked once per window. Time is a fake clock."""

import asyncio

import httpx

from app.infrastructure.ai.health import LanguageModelHealthCheck
from tests.ai_stubs import OPENROUTER_KEY_INFO, openrouter_error, openrouter_over


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Upstream:
    """Counts the calls that reach the provider and answers them with the next status."""

    def __init__(self, *statuses: int) -> None:
        self.calls = 0
        self._statuses = list(statuses)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        status = self._statuses.pop(0) if len(self._statuses) > 1 else self._statuses[0]
        body = OPENROUTER_KEY_INFO if status == 200 else openrouter_error(status)
        return httpx.Response(status, json=body)


def _check_over(
    upstream: _Upstream, clock: _Clock, *, cache_seconds: float = 30.0
) -> LanguageModelHealthCheck:
    return LanguageModelHealthCheck(
        openrouter_over(upstream), cache_seconds=cache_seconds, clock=clock
    )


async def test_repeated_checks_within_the_window_make_exactly_one_upstream_call() -> None:
    upstream, clock = _Upstream(200), _Clock()
    health_check = _check_over(upstream, clock)

    results = []
    for _ in range(5):
        results.append(await health_check.check())
        clock.now += 5

    assert results == [True] * 5
    assert upstream.calls == 1


async def test_a_failure_is_cached_for_the_same_window() -> None:
    """The provider recovers at once, but a failed check is no cheaper to repeat than a good one."""
    upstream, clock = _Upstream(401, 200), _Clock()
    health_check = _check_over(upstream, clock)

    assert await health_check.check() is False
    clock.now += 29.9
    assert await health_check.check() is False
    assert upstream.calls == 1


async def test_the_provider_is_asked_again_once_the_window_has_passed() -> None:
    upstream, clock = _Upstream(401, 200), _Clock()
    health_check = _check_over(upstream, clock)

    assert await health_check.check() is False
    clock.now += 30
    assert await health_check.check() is True
    assert upstream.calls == 2


async def test_concurrent_checks_share_one_upstream_call() -> None:
    upstream, clock = _Upstream(200), _Clock()
    health_check = _check_over(upstream, clock)

    results = await asyncio.gather(*(health_check.check() for _ in range(10)))

    assert results == [True] * 10
    assert upstream.calls == 1


async def test_a_zero_window_turns_the_cache_off() -> None:
    upstream, clock = _Upstream(200), _Clock()
    health_check = _check_over(upstream, clock, cache_seconds=0)

    await health_check.check()
    await health_check.check()

    assert upstream.calls == 2
