"""What the limiter does while its backend is unreachable: keep answering, warn once."""

import logging

import pytest
from app.application.ports.rate_limiter import RateLimitPolicy
from app.infrastructure.rate_limit.fail_open_rate_limiter import FailOpenRateLimiter
from app.infrastructure.rate_limit.in_memory_rate_limiter import InMemoryRateLimiter

from tests.rate_limit_fakes import (
    FakeClock,
    FakeMonotonic,
    HangingRateLimiter,
    SwitchableRateLimiter,
)

TWO_A_MINUTE = RateLimitPolicy(name="two-a-minute", limit=2, window_seconds=60)
LOGGER = "app.infrastructure.rate_limit.fail_open_rate_limiter"
RETRY_AFTER = 5.0


@pytest.fixture
def monotonic() -> FakeMonotonic:
    return FakeMonotonic()


@pytest.fixture
def primary() -> SwitchableRateLimiter:
    return SwitchableRateLimiter(InMemoryRateLimiter(clock=FakeClock()))


@pytest.fixture
def limiter(primary: SwitchableRateLimiter, monotonic: FakeMonotonic) -> FailOpenRateLimiter:
    return FailOpenRateLimiter(
        primary,
        InMemoryRateLimiter(clock=FakeClock()),
        retry_after_seconds=RETRY_AFTER,
        monotonic=monotonic,
    )


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.levelno == logging.WARNING]


async def test_a_healthy_primary_decides(
    limiter: FailOpenRateLimiter, caplog: pytest.LogCaptureFixture
) -> None:
    decisions = [await limiter.hit("ada", TWO_A_MINUTE) for _ in range(3)]

    assert [decision.allowed for decision in decisions] == [True, True, False]
    assert caplog.records == []


async def test_a_failing_primary_never_raises_and_the_request_is_allowed(
    limiter: FailOpenRateLimiter, primary: SwitchableRateLimiter
) -> None:
    primary.down = True

    decision = await limiter.hit("ada", TWO_A_MINUTE)

    assert decision.allowed is True


async def test_during_an_outage_the_fallback_still_limits_this_process(
    limiter: FailOpenRateLimiter, primary: SwitchableRateLimiter
) -> None:
    primary.down = True

    decisions = [await limiter.hit("ada", TWO_A_MINUTE) for _ in range(3)]

    assert [decision.allowed for decision in decisions] == [True, True, False]


async def test_an_outage_logs_one_warning_however_many_requests_it_spans(
    limiter: FailOpenRateLimiter,
    primary: SwitchableRateLimiter,
    monotonic: FakeMonotonic,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    primary.down = True

    for _ in range(4):  # spans several failed probes of the primary
        for _ in range(25):
            await limiter.hit("ada", TWO_A_MINUTE)
        monotonic.advance(RETRY_AFTER)

    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING


async def test_the_primary_is_left_alone_until_the_retry_interval_has_passed(
    limiter: FailOpenRateLimiter, primary: SwitchableRateLimiter, monotonic: FakeMonotonic
) -> None:
    primary.down = True
    for _ in range(10):
        await limiter.hit("ada", TWO_A_MINUTE)
    assert primary.calls == 1

    monotonic.advance(RETRY_AFTER - 0.1)
    await limiter.hit("ada", TWO_A_MINUTE)
    assert primary.calls == 1

    monotonic.advance(0.1)
    await limiter.hit("ada", TWO_A_MINUTE)
    await limiter.hit("ada", TWO_A_MINUTE)
    assert primary.calls == 2


async def test_recovery_returns_to_the_primary_and_is_logged_once(
    limiter: FailOpenRateLimiter,
    primary: SwitchableRateLimiter,
    monotonic: FakeMonotonic,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    primary.down = True
    await limiter.hit("ada", TWO_A_MINUTE)
    primary.down = False
    monotonic.advance(RETRY_AFTER)

    for _ in range(3):
        await limiter.hit("grace", TWO_A_MINUTE)

    assert primary.calls == 4
    assert [record.levelno for record in caplog.records] == [logging.WARNING, logging.INFO]


async def test_a_second_outage_is_warned_about_again(
    limiter: FailOpenRateLimiter,
    primary: SwitchableRateLimiter,
    monotonic: FakeMonotonic,
    caplog: pytest.LogCaptureFixture,
) -> None:
    primary.down = True
    await limiter.hit("ada", TWO_A_MINUTE)
    primary.down = False
    monotonic.advance(RETRY_AFTER)
    await limiter.hit("ada", TWO_A_MINUTE)

    primary.down = True
    await limiter.hit("ada", TWO_A_MINUTE)

    assert len(_warnings(caplog)) == 2


async def test_the_warning_names_the_error_type_but_never_its_message(
    limiter: FailOpenRateLimiter, primary: SwitchableRateLimiter, caplog: pytest.LogCaptureFixture
) -> None:
    primary.down = True

    await limiter.hit("ada", TWO_A_MINUTE)

    assert "ConnectionError" in caplog.text
    assert "s3cret-password" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


async def test_a_primary_that_hangs_is_abandoned_after_the_timeout(
    caplog: pytest.LogCaptureFixture,
) -> None:
    limiter = FailOpenRateLimiter(
        HangingRateLimiter(), InMemoryRateLimiter(clock=FakeClock()), timeout_seconds=0.01
    )

    decision = await limiter.hit("ada", TWO_A_MINUTE)

    assert decision.allowed is True
    assert len(_warnings(caplog)) == 1


async def test_the_in_memory_limiter_forgets_expired_keys() -> None:
    clock = FakeClock()
    limiter = InMemoryRateLimiter(clock=clock, max_keys=100)
    for index in range(100):
        await limiter.hit(f"ip:{index}", TWO_A_MINUTE)
    assert limiter.tracked_keys == 100

    clock.advance(60)
    await limiter.hit("ip:new", TWO_A_MINUTE)

    assert limiter.tracked_keys == 1


async def test_a_full_in_memory_limiter_allows_new_keys_instead_of_growing() -> None:
    limiter = InMemoryRateLimiter(clock=FakeClock(), max_keys=2)
    await limiter.hit("ip:1", TWO_A_MINUTE)
    await limiter.hit("ip:2", TWO_A_MINUTE)

    untracked = [await limiter.hit("ip:3", TWO_A_MINUTE) for _ in range(5)]

    assert all(decision.allowed for decision in untracked)
    assert limiter.tracked_keys == 2
    # Keys it already tracks are still limited.
    assert (await limiter.hit("ip:1", TWO_A_MINUTE)).allowed is True
    assert (await limiter.hit("ip:1", TWO_A_MINUTE)).allowed is False
