from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    """Who the provider says signed in, after the adapter verified the provider's answer.

    ``(provider, subject)`` is the stable key of the person. ``email`` is what the provider
    reports and ``email_verified`` whether the provider itself checked it: the adapter
    reports both faithfully and the use case decides what an unverified address may do.
    """

    provider: str
    subject: str
    email: str
    email_verified: bool
    full_name: str | None


class IdentityProvider(Protocol):
    """An external identity provider, driven with the authorization-code flow.

    The application never learns which provider this is or how it verifies a sign-in.
    Both operations are coroutines because a provider may have to ask the network where
    its endpoints are (OpenID Connect discovery).
    """

    @property
    def name(self) -> str: ...  # e.g. "google": the URL segment and the stored provider key

    async def authorization_url(self, *, state: str, nonce: str, redirect_uri: str) -> str:
        """Where to send the browser. ``state`` comes back on the callback untouched;
        ``nonce`` must come back inside the provider's verified answer.

        Raises ``IdentityProviderUnavailableError``.
        """
        ...

    async def exchange(self, *, code: str, redirect_uri: str, nonce: str) -> VerifiedIdentity:
        """Swap the callback's ``code`` for the identity of the person who signed in.

        Raises ``IdentityCodeRejectedError`` when the provider refuses the code or its answer
        fails verification (including a nonce other than ``nonce``), and
        ``IdentityProviderUnavailableError`` when the provider cannot be reached or refuses
        this application's own credentials. Neither error ever carries the code, the nonce
        or a token.
        """
        ...
