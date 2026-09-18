import time

from app.application.use_cases.check_readiness import CheckReadiness, CheckResult
from tests.fakes import HangingHealthCheck, RaisingHealthCheck, StubHealthCheck


async def test_all_healthy_is_ready() -> None:
    report = await CheckReadiness([StubHealthCheck("database"), StubHealthCheck("redis")]).execute()

    assert report.ready is True
    assert report.results == (CheckResult("database", True), CheckResult("redis", True))
    assert report.failed == ()


async def test_one_failing_is_not_ready_and_is_named() -> None:
    checks = [StubHealthCheck("database"), StubHealthCheck("redis", healthy=False)]

    report = await CheckReadiness(checks).execute()

    assert report.ready is False
    assert report.failed == ("redis",)


async def test_raising_check_is_marked_failed_without_crashing() -> None:
    checks = [RaisingHealthCheck("database"), StubHealthCheck("redis")]

    report = await CheckReadiness(checks).execute()

    assert report.ready is False
    assert report.results == (CheckResult("database", False), CheckResult("redis", True))


async def test_no_checks_is_ready() -> None:
    report = await CheckReadiness([]).execute()

    assert report.ready is True
    assert report.results == ()


async def test_timed_out_check_is_marked_failed() -> None:
    checks = [HangingHealthCheck("database"), StubHealthCheck("redis")]

    report = await CheckReadiness(checks, timeout_seconds=0.05).execute()

    assert report.failed == ("database",)


async def test_checks_run_concurrently_and_keep_registration_order() -> None:
    checks = [HangingHealthCheck("a"), HangingHealthCheck("b"), StubHealthCheck("c")]

    started = time.perf_counter()
    report = await CheckReadiness(checks, timeout_seconds=0.2).execute()
    elapsed = time.perf_counter() - started

    assert [result.name for result in report.results] == ["a", "b", "c"]
    assert elapsed < 0.35  # two 0.2s timeouts in parallel, not 0.4s in sequence
