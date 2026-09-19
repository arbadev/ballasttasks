"""uvicorn's access log records the full request target, query string included. The single
sign-on callback carries a state and a code there, so the application redacts it."""

import logging
from dataclasses import replace

import pytest
from fastapi import FastAPI

from app.api.access_log import RedactSsoQueryStrings
from app.application.sso import SsoConfig
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


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/sso/google/callback?code=4%2Fsecret-code&state=secret-state",
        "/auth/sso/google/callback?code=4%2Fsecret-code&state=secret-state",
    ],
)
def test_the_redaction_follows_the_path_the_api_is_published_under(path: str) -> None:
    """Served with a root path the log line carries the prefix; behind a proxy that strips
    it, it does not. Neither may show the query string."""
    record = access_record(path)

    assert RedactSsoQueryStrings("/api/v1").filter(record) is True

    line = record.getMessage()
    assert "secret" not in line
    assert path.partition("?")[0] + "?[redacted]" in line


def test_a_path_that_only_contains_the_single_sign_on_prefix_is_logged_as_it_came() -> None:
    record = access_record("/other/auth/sso/x?page=2")

    assert RedactSsoQueryStrings("/api/v1").filter(record) is True

    assert '"GET /other/auth/sso/x?page=2 HTTP/1.1"' in record.getMessage()


def test_the_application_redacts_under_the_path_of_its_public_api_url(
    tasks_app: FastAPI,
) -> None:
    container = replace(
        tasks_app.state.container,
        sso=SsoConfig(
            api_public_base_url="https://host.example/api",
            web_callback_url="https://host.example/auth/callback",
        ),
    )
    create_app(container=container)
    record = access_record("/api/auth/sso/google/callback?code=secret-code&state=secret-state")

    logging.getLogger("uvicorn.access").filter(record)

    line = record.getMessage()
    assert "secret" not in line
    assert "/api/auth/sso/google/callback?[redacted]" in line


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
