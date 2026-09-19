"""Google as an identity provider: OpenID Connect, authorization-code flow.

Written against Google's "OpenID Connect" guide
(https://developers.google.com/identity/openid-connect/openid-connect):

- the endpoints come from the discovery document, never from constants;
- the authorization request carries ``client_id``, ``response_type=code``,
  ``scope=openid email profile``, ``redirect_uri``, ``state`` and ``nonce``;
- the code is exchanged with a form POST to the token endpoint;
- the ID token is verified: signature against the keys at ``jwks_uri``, ``iss`` (the
  discovery issuer, with or without ``https://``, both of which Google documents), ``aud``
  equal to this client id (``azp`` too when present), ``exp``, and the ``nonce`` of this
  flow.

Discovery and keys are cached for as long as their ``Cache-Control: max-age`` allows. A
``kid`` that is not in the cache forces one early refetch (Google rotates keys), at most
once a minute, so made-up key ids cannot turn this adapter into a load generator.

No error carries a code, a nonce, a token or the client secret. The one thing logged is
the OAuth ``error`` code of a token response that blames this deployment's OAuth client
(a fixed vocabulary, matched against ``CLIENT_MISCONFIGURATION_ERRORS``), never the rest
of that response.
"""

import hmac
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar
from urllib.parse import urlencode

import httpx
import jwt

from app.application.errors import IdentityCodeRejectedError, IdentityProviderUnavailableError
from app.application.ports.identity_provider import VerifiedIdentity
from app.infrastructure.config.settings import ConfigurationError, Settings

logger = logging.getLogger(__name__)

GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
SCOPE = "openid email profile"
# Asymmetric only, and chosen here, never by the token: no ``alg=none``, no HS256 keyed
# with the public key. RS256 is the one algorithm Google's discovery document lists.
SIGNING_ALGORITHMS = ("RS256",)
REQUIRED_CLAIMS = ("iss", "sub", "aud", "exp", "iat")
# Token endpoint refusals that are about the OAuth client (a wrong or rotated secret, a
# redirect URI that is not registered), not about the code: no sign-in can succeed until an
# operator fixes the configuration.
CLIENT_MISCONFIGURATION_ERRORS = frozenset(
    {"invalid_client", "unauthorized_client", "redirect_uri_mismatch"}
)
CLOCK_SKEW_SECONDS = 30
MAX_SUBJECT_LENGTH = 255  # Google: "never exceeds 255 case-sensitive ASCII characters"
TIMEOUT = httpx.Timeout(5.0)

DEFAULT_MAX_AGE_SECONDS = 3600.0
MIN_MAX_AGE_SECONDS = 60.0
MAX_MAX_AGE_SECONDS = 86_400.0
FORCED_KEY_REFRESH_INTERVAL_SECONDS = 60.0

_MAX_AGE = re.compile(r"max-age=(\d+)")

ClientFactory = Callable[[], httpx.AsyncClient]


def _default_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT)


class _Secret:
    """Keeps the client secret out of reprs, and so out of tracebacks and debuggers."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "_Secret('**********')"


@dataclass(frozen=True, slots=True)
class _Cached[T]:
    value: T
    expires_at: float


class GoogleIdentityProvider:
    name: ClassVar[str] = "google"

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        client_factory: ClientFactory = _default_client,
        discovery_url: str = GOOGLE_DISCOVERY_URL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client_id = client_id
        self._client_secret = _Secret(client_secret)
        # One short-lived client per operation: sign-ins are rare, and nothing has to be
        # closed when the application stops.
        self._client_factory = client_factory
        self._discovery_url = discovery_url
        self._clock = clock
        self._discovery: _Cached[dict[str, str]] | None = None
        self._keys: _Cached[dict[str, jwt.PyJWK]] | None = None
        self._last_forced_key_refresh: float | None = None

    async def authorization_url(self, *, state: str, nonce: str, redirect_uri: str) -> str:
        async with self._client_factory() as client:
            discovery = await self._discover(client)
        query = urlencode(
            {
                "client_id": self._client_id,
                "response_type": "code",
                "scope": SCOPE,
                "redirect_uri": redirect_uri,
                "state": state,
                "nonce": nonce,
            }
        )
        return f"{discovery['authorization_endpoint']}?{query}"

    async def exchange(self, *, code: str, redirect_uri: str, nonce: str) -> VerifiedIdentity:
        async with self._client_factory() as client:
            discovery = await self._discover(client)
            id_token = await self._redeem(client, discovery["token_endpoint"], code, redirect_uri)
            key = await self._signing_key(client, discovery["jwks_uri"], id_token)
        claims = self._verified_claims(id_token, key, discovery["issuer"], nonce)
        return _identity(claims)

    # --- the three documents Google serves ------------------------------------------------

    async def _discover(self, client: httpx.AsyncClient) -> dict[str, str]:
        if self._discovery is None or self._discovery.expires_at <= self._clock():
            body, max_age = await self._get_json(client, self._discovery_url)
            endpoints = ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri")
            if not all(isinstance(body.get(name), str) and body[name] for name in endpoints):
                raise IdentityProviderUnavailableError
            self._discovery = _Cached(
                {name: body[name] for name in endpoints}, self._clock() + max_age
            )
        return self._discovery.value

    async def _signing_key(
        self, client: httpx.AsyncClient, jwks_uri: str, id_token: str
    ) -> jwt.PyJWK:
        try:
            kid = jwt.get_unverified_header(id_token).get("kid")
        except jwt.InvalidTokenError:
            raise IdentityCodeRejectedError from None
        if not isinstance(kid, str):
            raise IdentityCodeRejectedError
        if self._keys is None or self._keys.expires_at <= self._clock():
            await self._fetch_keys(client, jwks_uri)
        elif kid not in self._keys.value and self._may_force_a_key_refresh():
            self._last_forced_key_refresh = self._clock()
            await self._fetch_keys(client, jwks_uri)
        assert self._keys is not None  # noqa: S101  (set by _fetch_keys, or it raised)
        key = self._keys.value.get(kid)
        if key is None:
            raise IdentityCodeRejectedError
        return key

    def _may_force_a_key_refresh(self) -> bool:
        last = self._last_forced_key_refresh
        return last is None or self._clock() - last >= FORCED_KEY_REFRESH_INTERVAL_SECONDS

    async def _fetch_keys(self, client: httpx.AsyncClient, jwks_uri: str) -> None:
        body, max_age = await self._get_json(client, jwks_uri)
        keys: dict[str, jwt.PyJWK] = {}
        try:
            for jwk in body["keys"]:
                if jwk.get("use", "sig") == "sig" and isinstance(jwk.get("kid"), str):
                    try:
                        keys[jwk["kid"]] = jwt.PyJWK(jwk)
                    except jwt.PyJWTError:
                        # A key type or algorithm this PyJWT cannot load (Google may add
                        # one during a rotation) must not hide the keys it can.
                        continue
        except KeyError, TypeError, AttributeError:
            raise IdentityProviderUnavailableError from None
        if not keys:
            raise IdentityProviderUnavailableError
        self._keys = _Cached(keys, self._clock() + max_age)

    async def _get_json(self, client: httpx.AsyncClient, url: str) -> tuple[dict[str, Any], float]:
        try:
            response = await client.get(url)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError, ValueError:
            raise IdentityProviderUnavailableError from None
        if not isinstance(body, dict):
            raise IdentityProviderUnavailableError
        return body, _max_age(response)

    async def _redeem(
        self, client: httpx.AsyncClient, token_endpoint: str, code: str, redirect_uri: str
    ) -> str:
        try:
            response = await client.post(
                token_endpoint,
                data={
                    "code": code,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret.reveal(),
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        except httpx.HTTPError:
            raise IdentityProviderUnavailableError from None
        if response.status_code in {400, 401, 403}:
            error = _oauth_error(response)
            if error in CLIENT_MISCONFIGURATION_ERRORS:
                logger.warning(
                    "google refused this application's OAuth client: %s; check "
                    "SSO__GOOGLE_CLIENT_ID, SSO__GOOGLE_CLIENT_SECRET and the redirect URI "
                    "registered for SSO__API_PUBLIC_BASE_URL",
                    error,
                )
                raise IdentityProviderUnavailableError
            # ``invalid_grant`` and friends: Google looked at the code and said no.
            raise IdentityCodeRejectedError
        if response.status_code != httpx.codes.OK:
            raise IdentityProviderUnavailableError
        try:
            id_token = response.json().get("id_token")
        except ValueError, AttributeError:
            raise IdentityProviderUnavailableError from None
        if not isinstance(id_token, str) or not id_token:
            raise IdentityCodeRejectedError
        return id_token

    # --- ID token verification ------------------------------------------------------------

    def _verified_claims(
        self, id_token: str, key: jwt.PyJWK, issuer: str, nonce: str
    ) -> dict[str, Any]:
        try:
            claims: dict[str, Any] = jwt.decode(
                id_token,
                key,
                algorithms=list(SIGNING_ALGORITHMS),
                audience=self._client_id,
                issuer=[issuer, issuer.removeprefix("https://")],
                leeway=CLOCK_SKEW_SECONDS,
                options={"require": list(REQUIRED_CLAIMS)},
            )
        except jwt.PyJWTError:
            # ``from None``: PyJWT's message may quote a claim; ours never does.
            raise IdentityCodeRejectedError from None
        authorised_party = claims.get("azp")
        if authorised_party is not None and authorised_party != self._client_id:
            raise IdentityCodeRejectedError
        token_nonce = claims.get("nonce")
        if not isinstance(token_nonce, str) or not hmac.compare_digest(
            token_nonce.encode(), nonce.encode()
        ):
            raise IdentityCodeRejectedError
        return claims


def _identity(claims: dict[str, Any]) -> VerifiedIdentity:
    subject, email, name = claims.get("sub"), claims.get("email"), claims.get("name")
    if not isinstance(subject, str) or not 0 < len(subject) <= MAX_SUBJECT_LENGTH:
        raise IdentityCodeRejectedError
    if not isinstance(email, str) or not email:
        raise IdentityCodeRejectedError
    return VerifiedIdentity(
        provider=GoogleIdentityProvider.name,
        subject=subject,
        email=email,
        # Only a literal JSON ``true``: "true", 1 or a missing claim verify nothing.
        email_verified=claims.get("email_verified") is True,
        full_name=name if isinstance(name, str) else None,
    )


def _oauth_error(response: httpx.Response) -> str | None:
    """The ``error`` field of a token error response (RFC 6749, section 5.2), and nothing
    else of it: ``error_description`` is free text."""
    try:
        error = response.json().get("error")
    except ValueError, AttributeError:
        return None
    return error if isinstance(error, str) else None


def _max_age(response: httpx.Response) -> float:
    """ "Standard HTTP caching headers are used and should be respected": within bounds, so
    a missing or absurd header can neither disable the cache nor freeze a key set."""
    match = _MAX_AGE.search(response.headers.get("cache-control", ""))
    seconds = float(match.group(1)) if match else DEFAULT_MAX_AGE_SECONDS
    return min(max(seconds, MIN_MAX_AGE_SECONDS), MAX_MAX_AGE_SECONDS)


def build(settings: Settings) -> GoogleIdentityProvider:
    """Google needs an OAuth client: both halves, or the process does not start."""
    client_id = (settings.sso.google_client_id or "").strip()
    if not client_id:
        raise ConfigurationError(
            "SSO__GOOGLE_CLIENT_ID is required when 'google' is in SSO__ENABLED_PROVIDERS"
        )
    secret = settings.sso.google_client_secret
    client_secret = "" if secret is None else secret.get_secret_value().strip()
    if not client_secret:
        raise ConfigurationError(
            "SSO__GOOGLE_CLIENT_SECRET is required when 'google' is in SSO__ENABLED_PROVIDERS"
        )
    return GoogleIdentityProvider(client_id=client_id, client_secret=client_secret)
