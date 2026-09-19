"""Contract every IdentityProvider adapter must honour (Liskov).

Registering a new adapter = one new harness in ``HARNESSES``. A harness pairs the adapter
with "the person approves at the provider", which is the one step that differs: the fake
answers in its authorization URL, Google is played by ``tests.google_fakes.FakeGoogle``.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import pytest
from app.application.ports.identity_provider import IdentityProvider, VerifiedIdentity
from app.infrastructure.identity.fake import FakeIdentityProvider
from app.infrastructure.identity.google import GoogleIdentityProvider

from app.application.errors import IdentityCodeRejectedError
from tests.google_fakes import CLIENT_ID, CLIENT_SECRET, DISCOVERY_URL, FakeGoogle

REDIRECT_URI = "http://api.test/auth/sso/provider/callback"


@dataclass(frozen=True)
class Harness:
    provider: IdentityProvider
    # (authorization URL the adapter built) -> the code the provider sends to the callback
    approve: Callable[[str], Awaitable[str]]


def _fake() -> Harness:
    async def approve(authorization_url: str) -> str:
        return parse_qs(urlsplit(authorization_url).query)["code"][0]

    return Harness(FakeIdentityProvider(), approve)


def _google() -> Harness:
    google = FakeGoogle()

    async def approve(authorization_url: str) -> str:
        return google.approve(nonce=parse_qs(urlsplit(authorization_url).query)["nonce"][0])

    provider = GoogleIdentityProvider(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        client_factory=google.client,
        discovery_url=DISCOVERY_URL,
    )
    return Harness(provider, approve)


HARNESSES = [pytest.param(_fake, id="fake"), pytest.param(_google, id="google")]


@pytest.fixture(params=HARNESSES)
def harness(request: pytest.FixtureRequest) -> Harness:
    factory: Callable[[], Harness] = request.param
    return factory()


def test_the_name_is_a_short_lowercase_identifier(harness: Harness) -> None:
    name = harness.provider.name

    assert name
    assert name == name.lower()
    assert name.isidentifier()


async def test_the_authorization_url_is_absolute_and_round_trips_the_state(
    harness: Harness,
) -> None:
    url = await harness.provider.authorization_url(
        state="the-state", nonce="the-nonce", redirect_uri=REDIRECT_URI
    )

    parts = urlsplit(url)
    assert parts.scheme in {"http", "https"}
    assert parts.netloc
    assert parse_qs(parts.query)["state"] == ["the-state"]


async def test_an_approved_code_becomes_a_verified_identity_of_this_provider(
    harness: Harness,
) -> None:
    url = await harness.provider.authorization_url(
        state="the-state", nonce="the-nonce", redirect_uri=REDIRECT_URI
    )
    code = await harness.approve(url)

    identity = await harness.provider.exchange(
        code=code, redirect_uri=REDIRECT_URI, nonce="the-nonce"
    )

    assert isinstance(identity, VerifiedIdentity)
    assert identity.provider == harness.provider.name
    assert identity.subject
    assert "@" in identity.email
    assert isinstance(identity.email_verified, bool)


async def test_a_code_the_provider_never_issued_is_rejected(harness: Harness) -> None:
    await harness.provider.authorization_url(
        state="the-state", nonce="the-nonce", redirect_uri=REDIRECT_URI
    )

    with pytest.raises(IdentityCodeRejectedError):
        await harness.provider.exchange(
            code="never-issued", redirect_uri=REDIRECT_URI, nonce="the-nonce"
        )


async def test_a_code_works_once(harness: Harness) -> None:
    url = await harness.provider.authorization_url(
        state="the-state", nonce="the-nonce", redirect_uri=REDIRECT_URI
    )
    code = await harness.approve(url)
    await harness.provider.exchange(code=code, redirect_uri=REDIRECT_URI, nonce="the-nonce")

    with pytest.raises(IdentityCodeRejectedError):
        await harness.provider.exchange(code=code, redirect_uri=REDIRECT_URI, nonce="the-nonce")


async def test_a_code_approved_for_another_nonce_is_rejected(harness: Harness) -> None:
    """The nonce ties the provider's answer to the flow this browser started."""
    url = await harness.provider.authorization_url(
        state="the-state", nonce="the-nonce", redirect_uri=REDIRECT_URI
    )
    code = await harness.approve(url)

    with pytest.raises(IdentityCodeRejectedError):
        await harness.provider.exchange(code=code, redirect_uri=REDIRECT_URI, nonce="another-nonce")


async def test_a_rejection_never_repeats_the_code_or_the_nonce(harness: Harness) -> None:
    with pytest.raises(IdentityCodeRejectedError) as error:
        await harness.provider.exchange(
            code="secret-code-value", redirect_uri=REDIRECT_URI, nonce="secret-nonce-value"
        )

    assert "secret-code-value" not in str(error.value)
    assert "secret-nonce-value" not in str(error.value)
