import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.application.errors import UnknownIdentityProviderError
from app.application.ports.identity_provider import IdentityProvider
from app.application.ports.one_time_store import OneTimeStore
from app.application.sso import STATE_TTL, digest, new_secret, state_key


@dataclass(frozen=True, slots=True)
class SsoSignInStart:
    authorization_url: str
    # Goes to the browser that started the flow (an HttpOnly cookie) and nowhere else.
    browser_binding: str = field(repr=False)


class StartSsoSignIn:
    """Opens a sign-in: fresh state and nonce, remembered server-side for a few minutes and
    bound to the browser, then the provider's authorization URL.

    The state travels through the provider and back in URLs, so on its own it proves
    nothing about the browser presenting it. The binding is a second secret that only the
    starting browser holds; ``CompleteSsoSignIn`` demands both (no login CSRF).
    """

    def __init__(self, providers: Mapping[str, IdentityProvider], store: OneTimeStore) -> None:
        self._providers = providers
        self._store = store

    async def execute(self, *, provider: str, redirect_uri: str) -> SsoSignInStart:
        identity_provider = self._providers.get(provider)
        if identity_provider is None:
            raise UnknownIdentityProviderError
        state, nonce, binding = new_secret(), new_secret(), new_secret()
        authorization_url = await identity_provider.authorization_url(
            state=state, nonce=nonce, redirect_uri=redirect_uri
        )
        pending = {"provider": provider, "nonce": nonce, "binding": digest(binding)}
        await self._store.put(state_key(state), json.dumps(pending), ttl=STATE_TTL)
        return SsoSignInStart(authorization_url=authorization_url, browser_binding=binding)
