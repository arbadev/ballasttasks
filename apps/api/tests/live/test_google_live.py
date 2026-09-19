"""Opt-in check against the real Google endpoints: ``uv run pytest -m live``.

Needs a real OAuth client (``SSO__GOOGLE_CLIENT_ID`` and ``SSO__GOOGLE_CLIENT_SECRET``) and
network access; without them it is skipped, never failed. There is no browser here, so
what it proves is the wire contract: Google's real discovery document has the shape the
adapter reads, and Google's real token endpoint refuses a made-up code in the way the
adapter maps to ``IdentityCodeRejectedError``.
"""

from urllib.parse import parse_qs, urlsplit

import pytest
from app.infrastructure.identity.google import GoogleIdentityProvider
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.application.errors import IdentityCodeRejectedError
from app.infrastructure.config.settings import SsoSettings

pytestmark = pytest.mark.live

REDIRECT_URI = "http://localhost:8000/auth/sso/google/callback"


class _LiveSettings(BaseSettings):
    """Only the ``sso`` group, under its real variable names: a live run needs no database."""

    model_config = SettingsConfigDict(env_nested_delimiter="__", extra="ignore")

    sso: SsoSettings = SsoSettings()


@pytest.fixture
def provider() -> GoogleIdentityProvider:
    sso = _LiveSettings().sso
    if sso.google_client_id is None or sso.google_client_secret is None:
        pytest.skip(
            "no Google credentials: set SSO__GOOGLE_CLIENT_ID and SSO__GOOGLE_CLIENT_SECRET "
            "to run the live test"
        )
    return GoogleIdentityProvider(
        client_id=sso.google_client_id,
        client_secret=sso.google_client_secret.get_secret_value(),
    )


async def test_the_real_discovery_document_yields_googles_authorization_endpoint(
    provider: GoogleIdentityProvider,
) -> None:
    url = await provider.authorization_url(state="s", nonce="n", redirect_uri=REDIRECT_URI)

    parts = urlsplit(url)
    assert parts.scheme == "https"
    assert parts.netloc == "accounts.google.com"
    assert parse_qs(parts.query)["response_type"] == ["code"]


async def test_the_real_token_endpoint_refuses_a_made_up_code(
    provider: GoogleIdentityProvider,
) -> None:
    with pytest.raises(IdentityCodeRejectedError):
        await provider.exchange(code="4/made-up-code", redirect_uri=REDIRECT_URI, nonce="n")
