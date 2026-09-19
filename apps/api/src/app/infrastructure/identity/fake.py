"""An identity provider that needs no credentials: for tests and local demos only.

It "approves" immediately: its authorization URL is the callback itself, already carrying a
code, so the whole browser flow runs with no external page. It vouches for ``identity``
(by default one fixed demo person), which is why its factory refuses to build it when
``APP__ENV=production``.
"""

from collections import OrderedDict
from typing import ClassVar
from urllib.parse import urlencode

from app.application.errors import IdentityCodeRejectedError
from app.application.ports.identity_provider import VerifiedIdentity
from app.application.sso import new_secret
from app.infrastructure.config.settings import ConfigurationError, Settings

MAX_PENDING_CODES = 1_000


class FakeIdentityProvider:
    name: ClassVar[str] = "fake"

    DEMO_IDENTITY: ClassVar[VerifiedIdentity] = VerifiedIdentity(
        provider="fake",
        subject="fake-demo-user",
        email="demo.sso@example.com",
        email_verified=True,
        full_name="Demo SSO User",
    )

    def __init__(self, identity: VerifiedIdentity = DEMO_IDENTITY) -> None:
        # Who signs in next. Public on purpose: a test changes the person between flows.
        self.identity = identity
        self._codes: OrderedDict[str, tuple[str, str, VerifiedIdentity]] = OrderedDict()

    async def authorization_url(self, *, state: str, nonce: str, redirect_uri: str) -> str:
        code = new_secret()
        self._codes[code] = (nonce, redirect_uri, self.identity)
        while len(self._codes) > MAX_PENDING_CODES:
            self._codes.popitem(last=False)
        return f"{redirect_uri}?{urlencode({'code': code, 'state': state})}"

    async def exchange(self, *, code: str, redirect_uri: str, nonce: str) -> VerifiedIdentity:
        """Like a real provider: a code works once, for the redirect URI and the nonce it
        was issued with."""
        issued = self._codes.pop(code, None)
        if issued is None or issued[:2] != (nonce, redirect_uri):
            raise IdentityCodeRejectedError
        return issued[2]


def build(settings: Settings) -> FakeIdentityProvider:
    if settings.app.env == "production":
        raise ConfigurationError(
            "The 'fake' identity provider signs anybody in as its demo user: remove it from "
            "SSO__ENABLED_PROVIDERS, or do not run with APP__ENV=production"
        )
    return FakeIdentityProvider()
