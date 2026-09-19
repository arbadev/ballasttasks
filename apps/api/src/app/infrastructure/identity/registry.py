"""Provider name -> IdentityProvider factory.

Adding a provider: write the adapter, make it pass
``tests/contract/test_identity_provider_contract.py``, then add ONE line to
``IDENTITY_PROVIDERS``. Providers are switched on by name in ``SSO__ENABLED_PROVIDERS``.
Each factory owns its own "I need these credentials" rule and raises
``ConfigurationError`` naming the variable, so a misconfigured provider stops the process
at startup; a provider that is not enabled is never built and needs nothing.
"""

from collections.abc import Callable

from app.application.ports.identity_provider import IdentityProvider
from app.infrastructure.config.settings import ConfigurationError, Settings
from app.infrastructure.identity import fake, google

IdentityProviderFactory = Callable[[Settings], IdentityProvider]

IDENTITY_PROVIDERS: dict[str, IdentityProviderFactory] = {
    "fake": fake.build,
    "google": google.build,
}


def build_identity_providers(settings: Settings) -> dict[str, IdentityProvider]:
    """The enabled providers, in the order they are listed (the order the login screen
    shows them)."""
    providers: dict[str, IdentityProvider] = {}
    for name in settings.sso.enabled_providers:
        try:
            factory = IDENTITY_PROVIDERS[name]
        except KeyError:
            options = ", ".join(sorted(IDENTITY_PROVIDERS))
            raise ConfigurationError(
                f"SSO__ENABLED_PROVIDERS names {name!r}, which is not a registered provider. "
                f"Valid options: {options}"
            ) from None
        providers[name] = factory(settings)
    return providers
