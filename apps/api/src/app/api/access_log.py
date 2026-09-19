"""Keeps single sign-on secrets out of the access log.

uvicorn logs the full request target, query string included, and the callback's query
carries the provider's code and this application's state. The state is already spent when
the line is written, but "never in a log" is the rule, not "harmless in a log".

The API may be published under a path (``SSO__API_PUBLIC_BASE_URL=https://host/api``). Served
with a root path the logged target starts with it; behind a proxy that strips it, it does
not. Both forms are redacted.
"""

import logging

SSO_PATH_PREFIX = "/auth/sso/"
ACCESS_LOGGER = "uvicorn.access"
# uvicorn's access record: (client address, method, full path, HTTP version, status code)
_FULL_PATH = 2


class RedactSsoQueryStrings(logging.Filter):
    def __init__(self, public_path: str = "") -> None:
        super().__init__()
        self._prefixes = {SSO_PATH_PREFIX}
        self.cover(public_path)

    def cover(self, public_path: str) -> None:
        self._prefixes.add(f"{public_path}{SSO_PATH_PREFIX}")

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) > _FULL_PATH:
            path, separator, _ = str(args[_FULL_PATH]).partition("?")
            if separator and path.startswith(tuple(self._prefixes)):
                record.args = (
                    *args[:_FULL_PATH],
                    f"{path}?[redacted]",
                    *args[_FULL_PATH + 1 :],
                )
        return True


def install_access_log_redaction(public_path: str = "") -> None:
    """Idempotent: the application factory may run many times in one process (tests). One
    filter, which covers the public path of every application built here."""
    logger = logging.getLogger(ACCESS_LOGGER)
    for existing in logger.filters:
        if isinstance(existing, RedactSsoQueryStrings):
            existing.cover(public_path)
            return
    logger.addFilter(RedactSsoQueryStrings(public_path))
