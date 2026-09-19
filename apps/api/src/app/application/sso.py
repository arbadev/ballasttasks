"""What the single sign-on use cases share: lifetimes, store keys and the redirect targets.

Every secret of a flow (state, browser binding, exchange code) comes from ``new_secret`` and
reaches the ``OneTimeStore`` only as a SHA-256 digest: whoever can list the store's keys, or
read a stored value, learns nothing they could replay.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

# Long enough to pick an account and pass a second factor at the provider, no longer.
STATE_TTL = timedelta(minutes=5)
# The web app redeems the code the moment the browser lands on it.
EXCHANGE_CODE_TTL = timedelta(seconds=60)

_SECRET_BYTES = 32  # 256 bits from the operating system's CSPRNG
# Anything longer than this was not issued here; refuse it before hashing megabytes.
MAX_SECRET_LENGTH = 512


@dataclass(frozen=True, slots=True)
class SsoConfig:
    """The only redirect targets single sign-on ever uses. They come from settings, so
    nothing in a request can choose where a browser is sent."""

    api_public_base_url: str  # no trailing slash; the provider calls back under it
    web_callback_url: str  # where the web app receives the one-time code

    @property
    def cookies_are_secure(self) -> bool:
        return self.api_public_base_url.startswith("https://")

    @property
    def api_public_path(self) -> str:
        """The path the API is published under ("" at the root, else ``/api``): what a
        browser puts in front of every route, so cookie paths and log lines start with it."""
        return urlsplit(self.api_public_base_url).path.rstrip("/")


def new_secret() -> str:
    return secrets.token_urlsafe(_SECRET_BYTES)


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def state_key(state: str) -> str:
    return f"sso:state:{digest(state)}"


def exchange_code_key(code: str) -> str:
    return f"sso:exchange:{digest(code)}"
