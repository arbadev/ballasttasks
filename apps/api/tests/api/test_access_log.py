"""uvicorn's access log records the full request target, query string included. The single
sign-on callback carries a state and a code there, so the application redacts it."""

import logging

import pytest

from app.api.access_log import RedactSsoQueryStrings
from app.main import create_app


def access_record(path: str) -> logging.LogRecord:
    """A record shaped like uvicorn's: ``'%s - "%s %s HTTP/%s" %d'``."""
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:50000", "GET", path, "1.1", 303),
        exc_info=None,
    )


@pytest.mark.parametrize(
    "path",
    [
        "/auth/sso/google/callback?code=4%2Fsecret-code&state=secret-state",
        "/auth/sso/fake/callback?state=secret-state&error=access_denied",
        "/auth/sso/google/start?secret-state",
        "/auth/sso/exchange?code=secret-code",
    ],
)
def test_the_query_string_of_a_single_sign_on_request_is_not_logged(path: str) -> None:
    record = access_record(path)

    assert RedactSsoQueryStrings().filter(record) is True

    line = record.getMessage()
    assert "secret" not in line
    assert path.partition("?")[0] + "?[redacted]" in line
    assert line.startswith('127.0.0.1:50000 - "GET /auth/sso/')
    assert line.endswith('HTTP/1.1" 303')


@pytest.mark.parametrize("path", ["/tasks?status=done", "/auth/sso/providers", "/health"])
def test_every_other_request_is_logged_as_it_came(path: str) -> None:
    record = access_record(path)

    assert RedactSsoQueryStrings().filter(record) is True

    assert f'"GET {path} HTTP/1.1"' in record.getMessage()


@pytest.mark.parametrize("args", [None, (), ("only", "two"), {"a": "mapping"}])
def test_a_record_that_is_not_shaped_like_an_access_line_passes_untouched(args: object) -> None:
    record = access_record("/auth/sso/google/callback?state=s")
    record.args = args  # type: ignore[assignment]

    assert RedactSsoQueryStrings().filter(record) is True
    assert record.args == args


def test_the_application_installs_the_redaction_once(tasks_app: object) -> None:
    create_app(container=tasks_app.state.container)  # type: ignore[attr-defined]

    installed = [
        f
        for f in logging.getLogger("uvicorn.access").filters
        if isinstance(f, RedactSsoQueryStrings)
    ]
    assert len(installed) == 1
