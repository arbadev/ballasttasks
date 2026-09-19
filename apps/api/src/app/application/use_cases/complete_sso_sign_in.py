import hmac
import json
from collections.abc import Mapping

from app.application.errors import (
    IdentityCodeRejectedError,
    SsoStateInvalidError,
    UnknownIdentityProviderError,
)
from app.application.ports.identity_provider import IdentityProvider
from app.application.ports.one_time_store import OneTimeStore
from app.application.sso import (
    EXCHANGE_CODE_TTL,
    MAX_SECRET_LENGTH,
    digest,
    exchange_code_key,
    new_secret,
    state_key,
)
from app.application.use_cases.sign_in_with_identity import SignInWithIdentity


class CompleteSsoSignIn:
    """Handles the provider's callback and returns a one-time exchange code.

    The state is taken (so spent) before anything is checked: a replay, a tampered value and
    a callback in the wrong browser all find nothing to use. Only then is the provider asked
    who signed in, the user found or created, and a code issued that the web app swaps for
    the access token. The code stands for a user id; the token itself is never stored and
    never travels in a URL.
    """

    def __init__(
        self,
        providers: Mapping[str, IdentityProvider],
        store: OneTimeStore,
        sign_in: SignInWithIdentity,
    ) -> None:
        self._providers = providers
        self._store = store
        self._sign_in = sign_in

    async def execute(
        self,
        *,
        provider: str,
        state: str | None,
        code: str | None,
        browser_binding: str | None,
        redirect_uri: str,
    ) -> str:
        identity_provider = self._providers.get(provider)
        if identity_provider is None:
            raise UnknownIdentityProviderError
        nonce = await self._spend_state(provider, state, browser_binding)
        if not code:
            # The person declined at the provider, or the URL was cut short.
            raise SsoStateInvalidError

        identity = await identity_provider.exchange(
            code=code, redirect_uri=redirect_uri, nonce=nonce
        )
        if identity.provider != provider:
            # An adapter may only vouch for itself: (provider, subject) is the account key.
            raise IdentityCodeRejectedError
        user = await self._sign_in.execute(identity)

        exchange_code = new_secret()
        await self._store.put(exchange_code_key(exchange_code), str(user.id), ttl=EXCHANGE_CODE_TTL)
        return exchange_code

    async def _spend_state(
        self, provider: str, state: str | None, browser_binding: str | None
    ) -> str:
        if not state or len(state) > MAX_SECRET_LENGTH:
            raise SsoStateInvalidError
        stored = await self._store.take(state_key(state))
        if stored is None or not browser_binding or len(browser_binding) > MAX_SECRET_LENGTH:
            raise SsoStateInvalidError
        pending = json.loads(stored)
        same_browser = hmac.compare_digest(digest(browser_binding), pending["binding"])
        if not same_browser or pending["provider"] != provider:
            raise SsoStateInvalidError
        return str(pending["nonce"])
