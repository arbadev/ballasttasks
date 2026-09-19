from collections.abc import Callable
from datetime import UTC, date, datetime

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def today_utc(clock: Clock) -> date:
    """The calendar day every date rule is evaluated against: the clock's instant, in UTC.

    "Today", "overdue" and "due soon" therefore change at 00:00 UTC for everybody, wherever
    they are; a user west of Greenwich sees a task turn overdue before their own midnight.
    Per-user time zones are out of scope (see "Time" in ``docs/architecture.md``).
    """
    return clock().astimezone(UTC).date()
