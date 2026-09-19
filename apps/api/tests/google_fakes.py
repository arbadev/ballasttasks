"""A stand-in for Google's OpenID Connect endpoints, served through ``httpx.MockTransport``.

Discovery document, JWKS and token endpoint, with signing keys generated here: nothing
leaves the process and no Google credential is needed. Every knob a test turns is a
public attribute, so a test reads as "Google answers this, the adapter must do that".
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "https://accounts.google.test"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
AUTHORIZATION_ENDPOINT = f"{ISSUER}/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.google.test/token"
JWKS_URI = "https://www.google.test/oauth2/v3/certs"

CLIENT_ID = "client-id.apps.google.test"
CLIENT_SECRET = "client-secret-never-shown"


@dataclass(frozen=True)
class SigningKey:
    kid: str
    private_key: rsa.RSAPrivateKey

    @classmethod
    def generate(cls) -> SigningKey:
        return cls(
            kid=uuid.uuid4().hex,
            private_key=rsa.generate_private_key(public_exponent=65537, key_size=2048),
        )

    def jwk(self) -> dict[str, Any]:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.private_key.public_key()))
        return {**jwk, "kid": self.kid, "use": "sig", "alg": "RS256"}


@dataclass
class FakeGoogle:
    """Answers what Google would. ``requests`` records every call the adapter made."""

    keys: list[SigningKey] = field(default_factory=lambda: [SigningKey.generate()])
    codes: dict[str, dict[str, Any]] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)
    jwks_max_age: int = 3600
    discovery_status: int = 200
    jwks_status: int = 200
    token_status: int | None = None
    token_body: dict[str, Any] | None = None
    network_down: bool = False

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport())

    def count(self, url: str) -> int:
        return sum(1 for request in self.requests if str(request.url) == url)

    def claims(self, *, nonce: str, **overrides: Any) -> dict[str, Any]:
        """The ID token claims of a well-behaved sign-in; a test overrides what it breaks."""
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "azp": CLIENT_ID,
            "sub": "110169484474386276334",
            "email": "ada@example.com",
            "email_verified": True,
            "name": "Ada Lovelace",
            "nonce": nonce,
            "iat": now,
            "exp": now + 3600,
        }
        claims.update(overrides)
        return {name: value for name, value in claims.items() if value is not None}

    def sign(self, claims: dict[str, Any], *, key: SigningKey | None = None, **kwargs: Any) -> str:
        key = key or self.keys[0]
        return jwt.encode(
            claims, key.private_key, algorithm="RS256", headers={"kid": key.kid}, **kwargs
        )

    def grant(self, *, id_token: str) -> str:
        """An authorization code the token endpoint will swap for ``id_token``."""
        code = f"4/{uuid.uuid4().hex}"
        self.codes[code] = {
            "access_token": "ya29.access-token-never-used",
            "expires_in": 3599,
            "scope": "openid email profile",
            "token_type": "Bearer",
            "id_token": id_token,
        }
        return code

    def approve(self, *, nonce: str, **claim_overrides: Any) -> str:
        return self.grant(id_token=self.sign(self.claims(nonce=nonce, **claim_overrides)))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.network_down:
            raise httpx.ConnectError("connection refused", request=request)
        url = str(request.url)
        if url == DISCOVERY_URL:
            return httpx.Response(
                self.discovery_status,
                headers={"Cache-Control": "public, max-age=3600"},
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": AUTHORIZATION_ENDPOINT,
                    "token_endpoint": TOKEN_ENDPOINT,
                    "jwks_uri": JWKS_URI,
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        if url == JWKS_URI:
            return httpx.Response(
                self.jwks_status,
                headers={"Cache-Control": f"public, max-age={self.jwks_max_age}, must-revalidate"},
                json={"keys": [key.jwk() for key in self.keys]},
            )
        if url == TOKEN_ENDPOINT and request.method == "POST":
            return self._token(request)
        return httpx.Response(404)

    def _token(self, request: httpx.Request) -> httpx.Response:
        if self.token_status is not None:
            return httpx.Response(self.token_status, json=self.token_body or {})
        form = {name: values[0] for name, values in parse_qs(request.content.decode()).items()}
        granted = self.codes.pop(form.get("code", ""), None)
        well_formed = (
            form.get("grant_type") == "authorization_code"
            and form.get("client_id") == CLIENT_ID
            and form.get("client_secret") == CLIENT_SECRET
            and bool(form.get("redirect_uri"))
        )
        if granted is None or not well_formed:
            return httpx.Response(
                400, json={"error": "invalid_grant", "error_description": "Bad Request"}
            )
        return httpx.Response(200, json=self.token_body or granted)
