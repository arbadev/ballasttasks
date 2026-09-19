import uuid

import pytest


@pytest.fixture(autouse=True)
def rate_limit_keys_of_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every integration test counts under a key prefix of its own.

    They all call from one address into one real Redis, where a count outlives the test that
    made it: without this, the logins of one test would use up the budget of the next. The
    limiter stays on, and the keys expire on their own, so nothing is deleted from that Redis.
    """
    monkeypatch.setenv("RATE_LIMIT__KEY_PREFIX", f"ratelimit-test-{uuid.uuid4().hex}")
