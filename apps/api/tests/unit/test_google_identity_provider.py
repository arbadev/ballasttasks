"""GoogleIdentityProvider against a stand-in Google (``httpx.MockTransport``, local keys).

What every adapter shares is in ``tests/contract/test_identity_provider_contract.py``;
this module is what is specific to OpenID Connect: the requests Google documents, and one
test per way an ID token can be wrong.
"""

import base64
import hmac
import json
import logging
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization

from app.application.errors import IdentityCodeRejectedError, IdentityProviderUnavailableError
from app.infrastructure.identity.google import GoogleIdentityProvider
from tests.google_fakes import (
    AUTHORIZATION_ENDPOINT,
    CLIENT_ID,
    CLIENT_SECRET,
    DISCOVERY_URL,
    ISSUER,
    JWKS_URI,
    TOKEN_ENDPOINT,
    FakeGoogle,
    SigningKey,
)

REDIRECT_URI = "https://api.example/auth/sso/google/callback"
NONCE = "nonce-of-this-flow"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class ManualClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def provider(google: FakeGoogle, clock: ManualClock) -> GoogleIdentityProvider:
    return GoogleIdentityProvider(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        client_factory=google.client,
        discovery_url=DISCOVERY_URL,
        clock=clock,
    )


async def exchange(provider: GoogleIdentityProvider, code: str, nonce: str = NONCE) -> Any:
    return await provider.exchange(code=code, redirect_uri=REDIRECT_URI, nonce=nonce)


def test_it_is_named_google(provider: GoogleIdentityProvider) -> None:
    assert provider.name == "google"


async def test_the_authorization_url_is_the_documented_code_flow_request(
    provider: GoogleIdentityProvider,
) -> None:
    url = await provider.authorization_url(state="s-1", nonce=NONCE, redirect_uri=REDIRECT_URI)

    assert url.startswith(f"{AUTHORIZATION_ENDPOINT}?")
    assert parse_qs(urlsplit(url).query) == {
        "client_id": [CLIENT_ID],
        "response_type": ["code"],
        "scope": ["openid email profile"],
        "redirect_uri": [REDIRECT_URI],
        "state": ["s-1"],
        "nonce": [NONCE],
    }
    assert CLIENT_SECRET not in url


async def test_the_code_is_exchanged_with_the_documented_form_post(
    provider: GoogleIdentityProvider, google: FakeGoogle
) -> None:
    code = google.approve(nonce=NONCE)

    await exchange(provider, code)

    request = next(r for r in google.requests if str(r.url) == TOKEN_ENDPOINT)
    assert request.method == "POST"
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert parse_qs(request.content.decode()) == {
        "code": [code],
        "client_id": [CLIENT_ID],
        "client_secret": [CLIENT_SECRET],
        "redirect_uri": [REDIRECT_URI],
        "grant_type": ["authorization_code"],
    }


async def test_the_identity_is_read_from_the_id_token_claims(
    provider: GoogleIdentityProvider, google: FakeGoogle
) -> None:
    code = google.approve(nonce=NONCE, sub="1234567890", email="Grace@Example.com", name="Grace")

    identity = await exchange(provider, code)

    assert identity.provider == "google"
    assert identity.subject == "1234567890"
    assert identity.email == "Grace@Example.com"
    assert identity.email_verified is True
    assert identity.full_name == "Grace"


@pytest.mark.parametrize("claim", [False, None, "true", 1])
async def test_only_a_literal_true_counts_as_a_verified_email(
    provider: GoogleIdentityProvider, google: FakeGoogle, claim: object
) -> None:
    identity = await exchange(provider, google.approve(nonce=NONCE, email_verified=claim))

    assert identity.email_verified is False


async def test_a_missing_name_is_reported_as_none(
    provider: GoogleIdentityProvider, google: FakeGoogle
) -> None:
    identity = await exchange(provider, google.approve(nonce=NONCE, name=None))

    assert identity.full_name is None


async def test_googles_issuer_without_a_scheme_is_accepted(
    provider: GoogleIdentityProvider, google: FakeGoogle
) -> None:
    """Google documents both ``https://accounts.google.com`` and ``accounts.google.com``."""
    code = google.approve(nonce=NONCE, iss=ISSUER.removeprefix("https://"))

    assert (await exchange(provider, code)).subject


REJECTED_CLAIMS = {
    "wrong audience": {"aud": "another-client.apps.google.test", "azp": None},
    "audience list that does not name this client": {"aud": ["a", "b"], "azp": None},
    "this client among other audiences, authorised party is another": {
        "aud": [CLIENT_ID, "another-client"],
        "azp": "another-client",
    },
    "wrong issuer": {"iss": "https://accounts.evil.test"},
    "issuer that only starts like the real one": {"iss": ISSUER + ".evil.test"},
    "expired": {"iat": int(time.time()) - 7200, "exp": int(time.time()) - 3600},
    "issued in the future": {"iat": int(time.time()) + 3600, "exp": int(time.time()) + 7200},
    "wrong nonce": {"nonce": "nonce-of-another-flow"},
    "no nonce": {"nonce": None},
    "no subject": {"sub": None},
    "empty subject": {"sub": ""},
    "subject too long to be one": {"sub": "9" * 256},
    "no email": {"email": None},
    "no expiry": {"exp": None},
    "no issuer": {"iss": None},
    "no audience": {"aud": None},
}


@pytest.mark.parametrize("overrides", REJECTED_CLAIMS.values(), ids=REJECTED_CLAIMS.keys())
async def test_an_id_token_with_a_wrong_claim_is_rejected(
    provider: GoogleIdentityProvider, google: FakeGoogle, overrides: dict[str, Any]
) -> None:
    code = google.approve(**{"nonce": NONCE, **overrides})

    with pytest.raises(IdentityCodeRejectedError):
        await exchange(provider, code)


async def test_a_signature_by_a_key_google_does_not_publish_is_rejected(
    provider: GoogleIdentityProvider, google: FakeGoogle
) -> None:
    """Same ``kid`` as the published key, so only the signature check can tell."""
    forger = SigningKey(kid=google.keys[0].kid, private_key=SigningKey.generate().private_key)
    code = google.grant(id_token=google.sign(google.claims(nonce=NONCE), key=forger))

    with pytest.raises(IdentityCodeRejectedError):
        await exchange(provider, code)


async def test_a_tampered_payload_is_rejected(
    provider: GoogleIdentityProvider, google: FakeGoogle
) -> None:
    header, _, signature = google.sign(google.claims(nonce=NONCE)).split(".")
    forged = google.claims(nonce=NONCE, email="attacker@example.com")
    payload = _b64(json.dumps(forged).encode())

    with pytest.raises(IdentityCodeRejectedError):
        await exchange(provider, google.grant(id_token=f"{header}.{payload}.{signature}"))


async def test_an_unsigned_id_token_is_rejected(
    provider: GoogleIdentityProvider, google: FakeGoogle
) -> None:
    unsigned = jwt.encode(
        google.claims(nonce=NONCE),
        None,  # type: ignore[arg-type]  # PyJWT's own way to build an ``alg=none`` token
        algorithm="none",
        headers={"kid": google.keys[0].kid},
    )

    with pytest.raises(IdentityCodeRejectedError):
        await exchange(provider, google.grant(id_token=unsigned))


async def test_an_hmac_token_keyed_with_the_public_key_is_rejected(
    provider: GoogleIdentityProvider, google: FakeGoogle
) -> None:
    """Algorithm confusion: the verifier must never let the token choose HS256. PyJWT
    refuses to even build such a token, so the attacker's token is assembled by hand."""
    public_pem = (
        google.keys[0]
        .private_key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": google.keys[0].kid}).encode())
    payload = _b64(json.dumps(google.claims(nonce=NONCE)).encode())
    signature = _b64(hmac.new(public_pem, f"{header}.{payload}".encode(), "sha256").digest())

    with pytest.raises(IdentityCodeRejectedError):
        await exchange(provider, google.grant(id_token=f"{header}.{payload}.{signature}"))


@pytest.mark.parametrize("id_token", ["", "not-a-jwt", "a.b.c", None, 42])
async def test_a_token_response_without_a_usable_id_token_is_rejected(
    provider: GoogleIdentityProvider, google: FakeGoogle, id_token: object
) -> None:
    google.token_body = {"access_token": "ya29", "token_type": "Bearer", "id_token": id_token}

    with pytest.raises(IdentityCodeRejectedError):
        await exchange(provider, google.approve(nonce=NONCE))


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_a_code_google_refuses_is_rejected(
    provider: GoogleIdentityProvider, google: FakeGoogle, status: int
) -> None:
    google.token_status = status
    google.token_body = {"error": "invalid_grant"}

    with pytest.raises(IdentityCodeRejectedError):
        await exchange(provider, "4/some-code")


@pytest.mark.parametrize("status", [400, 401])
@pytest.mark.parametrize(
    "error", ["invalid_client", "unauthorized_client", "redirect_uri_mismatch"]
)
async def test_a_refusal_that_blames_the_oauth_client_is_an_unreachable_provider_and_a_warning(
    provider: GoogleIdentityProvider,
    google: FakeGoogle,
    caplog: pytest.LogCaptureFixture,
    status: int,
    error: str,
) -> None:
    """A wrong or rotated client secret is the operator's problem, not a bad code: the
    person is told to try again later and the operator gets a line that names the cause."""
    google.token_status = status
    google.token_body = {"error": error, "error_description": "described-by-google"}
    code = "4/some-secret-code"

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(IdentityProviderUnavailableError) as raised,
    ):
        await exchange(provider, code)

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert error in warnings[0].getMessage()
    shown = f"{caplog.text} {raised.value!s} {raised.value!r} {raised.value.__cause__!r}"
    for secret in (code, CLIENT_SECRET, NONCE, "described-by-google"):
        assert secret not in shown
    assert str(raised.value) == str(IdentityProviderUnavailableError())


@pytest.mark.parametrize(
    "body",
    [
        {"error": "invalid_grant", "error_description": "described-by-google"},
        {"error": "something-google-made-up"},
        {"error": ["invalid_client"]},
        {"error_description": "invalid_client"},
        {},
    ],
)
async def test_any_other_refusal_is_a_rejected_code_and_logs_nothing(
    provider: GoogleIdentityProvider,
    google: FakeGoogle,
    caplog: pytest.LogCaptureFixture,
    body: dict[str, Any],
) -> None:
    google.token_status = 400
    google.token_body = body

    with caplog.at_level(logging.DEBUG), pytest.raises(IdentityCodeRejectedError):
        await exchange(provider, "4/some-code")

    assert [r for r in caplog.records if r.name.startswith("app.")] == []


async def test_a_refusal_that_is_not_json_is_a_rejected_code(
    clock: ManualClock, google: FakeGoogle
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_ENDPOINT:
            return httpx.Response(400, text="invalid_client")
        return google.transport().handle_request(request)

    provider = GoogleIdentityProvider(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        discovery_url=DISCOVERY_URL,
        clock=clock,
    )

    with pytest.raises(IdentityCodeRejectedError):
        await exchange(provider, "4/some-code")


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_a_token_endpoint_in_trouble_is_an_unreachable_provider(
    provider: GoogleIdentityProvider, google: FakeGoogle, status: int
) -> None:
    google.token_status = status

    with pytest.raises(IdentityProviderUnavailableError):
        await exchange(provider, "4/some-code")


async def test_no_network_is_an_unreachable_provider_for_both_operations(
    provider: GoogleIdentityProvider, google: FakeGoogle
) -> None:
    google.network_down = True

    with pytest.raises(IdentityProviderUnavailableError):
        await provider.authorization_url(state="s", nonce=NONCE, redirect_uri=REDIRECT_URI)
    with pytest.raises(IdentityProviderUnavailableError):
        await exchange(provider, "4/some-code")


async def test_a_timeout_is_an_unreachable_provider(clock: ManualClock) -> None:
    def too_slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    provider = GoogleIdentityProvider(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(too_slow)),
        discovery_url=DISCOVERY_URL,
        clock=clock,
    )

    with pytest.raises(IdentityProviderUnavailableError):
        await exchange(provider, "4/some-code")


@pytest.mark.parametrize("broken", ["discovery_status", "jwks_status"])
async def test_a_broken_discovery_or_key_document_is_an_unreachable_provider(
    provider: GoogleIdentityProvider, google: FakeGoogle, broken: str
) -> None:
    setattr(google, broken, 500)

    with pytest.raises(IdentityProviderUnavailableError):
        await exchange(provider, google.approve(nonce=NONCE))


async def test_a_discovery_document_that_is_not_the_expected_shape_is_an_unreachable_provider(
    clock: ManualClock,
) -> None:
    provider = GoogleIdentityProvider(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"issuer": ISSUER}))
        ),
        discovery_url=DISCOVERY_URL,
        clock=clock,
    )

    with pytest.raises(IdentityProviderUnavailableError):
        await provider.authorization_url(state="s", nonce=NONCE, redirect_uri=REDIRECT_URI)


async def test_discovery_and_keys_are_fetched_once_and_reused_until_they_expire(
    provider: GoogleIdentityProvider, google: FakeGoogle, clock: ManualClock
) -> None:
    google.jwks_max_age = 600
    for _ in range(3):
        await exchange(provider, google.approve(nonce=NONCE))
    assert google.count(DISCOVERY_URL) == 1
    assert google.count(JWKS_URI) == 1

    clock.now += 599
    await exchange(provider, google.approve(nonce=NONCE))
    assert google.count(JWKS_URI) == 1

    clock.now += 2
    await exchange(provider, google.approve(nonce=NONCE))
    assert google.count(JWKS_URI) == 2

    clock.now += 3600
    await exchange(provider, google.approve(nonce=NONCE))
    assert google.count(DISCOVERY_URL) == 2


async def test_a_key_google_rotated_in_is_picked_up_without_waiting_for_the_cache(
    provider: GoogleIdentityProvider, google: FakeGoogle
) -> None:
    await exchange(provider, google.approve(nonce=NONCE))
    rotated = SigningKey.generate()
    google.keys = [rotated]

    identity = await exchange(
        provider, google.grant(id_token=google.sign(google.claims(nonce=NONCE), key=rotated))
    )

    assert identity.subject
    assert google.count(JWKS_URI) == 2


async def test_unknown_key_ids_cannot_make_the_adapter_hammer_the_key_endpoint(
    provider: GoogleIdentityProvider, google: FakeGoogle, clock: ManualClock
) -> None:
    await exchange(provider, google.approve(nonce=NONCE))
    for _ in range(5):
        stranger = SigningKey.generate()
        code = google.grant(id_token=google.sign(google.claims(nonce=NONCE), key=stranger))
        with pytest.raises(IdentityCodeRejectedError):
            await exchange(provider, code)

    assert google.count(JWKS_URI) == 2

    clock.now += 61
    stranger = SigningKey.generate()
    code = google.grant(id_token=google.sign(google.claims(nonce=NONCE), key=stranger))
    with pytest.raises(IdentityCodeRejectedError):
        await exchange(provider, code)
    assert google.count(JWKS_URI) == 3


async def test_no_error_ever_carries_the_code_the_secret_or_the_id_token(
    provider: GoogleIdentityProvider, google: FakeGoogle
) -> None:
    id_token = google.sign(google.claims(nonce=NONCE, aud="someone-else"))
    code = google.grant(id_token=id_token)

    with pytest.raises(IdentityCodeRejectedError) as error:
        await exchange(provider, code)

    shown = f"{error.value!s} {error.value!r} {error.value.__cause__!r} {error.value.__context__!r}"
    for secret in (code, CLIENT_SECRET, id_token, NONCE):
        assert secret not in shown


def test_the_secret_is_not_in_the_adapters_repr(provider: GoogleIdentityProvider) -> None:
    assert CLIENT_SECRET not in repr(provider)
    assert CLIENT_SECRET not in str(vars(provider) if hasattr(provider, "__dict__") else "")


async def test_an_id_token_without_a_key_id_is_rejected(
    provider: GoogleIdentityProvider, google: FakeGoogle
) -> None:
    no_kid = jwt.encode(google.claims(nonce=NONCE), google.keys[0].private_key, algorithm="RS256")

    with pytest.raises(IdentityCodeRejectedError):
        await exchange(provider, google.grant(id_token=no_kid))


@pytest.mark.parametrize(
    "document",
    [[], {"keys": "not-a-list"}, {"keys": [{"kid": "k", "kty": "RSA"}]}, {"no": "keys"}],
)
async def test_a_key_document_that_is_not_a_jwk_set_is_an_unreachable_provider(
    clock: ManualClock, google: FakeGoogle, document: object
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == JWKS_URI:
            return httpx.Response(200, json=document)
        return google.transport().handle_request(request)

    provider = GoogleIdentityProvider(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        discovery_url=DISCOVERY_URL,
        clock=clock,
    )

    with pytest.raises(IdentityProviderUnavailableError):
        await exchange(provider, google.approve(nonce=NONCE))


async def test_a_published_key_pyjwt_cannot_load_does_not_hide_the_usable_ones(
    clock: ManualClock, google: FakeGoogle
) -> None:
    """Google adds a key of a type this PyJWT does not know during a rotation: the key
    that signed the token is still there."""
    unloadable = [
        {"kid": "from-the-future", "use": "sig", "kty": "XYZ", "alg": "XY512"},
        {"kid": "half-a-key", "use": "sig", "kty": "RSA"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == JWKS_URI:
            published = [*unloadable, *(key.jwk() for key in google.keys)]
            return httpx.Response(200, json={"keys": published})
        return google.transport().handle_request(request)

    provider = GoogleIdentityProvider(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        discovery_url=DISCOVERY_URL,
        clock=clock,
    )

    identity = await exchange(provider, google.approve(nonce=NONCE))

    assert identity.subject == "110169484474386276334"


async def test_a_token_response_that_is_not_json_is_an_unreachable_provider(
    clock: ManualClock, google: FakeGoogle
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_ENDPOINT:
            return httpx.Response(200, text="<html>captive portal</html>")
        return google.transport().handle_request(request)

    provider = GoogleIdentityProvider(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        discovery_url=DISCOVERY_URL,
        clock=clock,
    )

    with pytest.raises(IdentityProviderUnavailableError):
        await exchange(provider, "4/some-code")


def test_the_default_client_has_a_timeout() -> None:
    provider = GoogleIdentityProvider(client_id=CLIENT_ID, client_secret=CLIENT_SECRET)

    client = provider._client_factory()

    assert client.timeout.connect is not None
    assert client.timeout.read is not None
