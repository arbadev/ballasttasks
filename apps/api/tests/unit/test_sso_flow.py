"""The three steps of a browser sign-in, as use cases with in-memory fakes.

start (state, nonce, browser binding) -> complete (validate, exchange, find or create the
user, one-time code) -> redeem (one-time code for the access token).
"""

import dataclasses
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from app.application.ports.identity_provider import IdentityProvider
from app.application.sso import EXCHANGE_CODE_TTL, STATE_TTL
from app.application.use_cases.complete_sso_sign_in import CompleteSsoSignIn
from app.application.use_cases.redeem_sso_code import RedeemSsoCode
from app.application.use_cases.sign_in_with_identity import SignInWithIdentity
from app.application.use_cases.start_sso_sign_in import SsoSignInStart, StartSsoSignIn
from app.infrastructure.identity.fake import FakeIdentityProvider

from app.application.errors import (
    EmailNotVerifiedError,
    IdentityCodeRejectedError,
    IdentityProviderUnavailableError,
    InvalidSsoCodeError,
    SsoStateInvalidError,
    UnknownIdentityProviderError,
    UserNotActiveError,
)
from tests.auth_fakes import FakeTokenService, InMemoryUserRepository, a_user
from tests.sso_fakes import (
    InMemoryOneTimeStore,
    InMemoryUserIdentityRepository,
    MutableClock,
    StubIdentityProvider,
    an_identity,
)

REDIRECT_URI = "http://api.test/auth/sso/fake/callback"


@dataclass
class Flow:
    clock: MutableClock
    store: InMemoryOneTimeStore
    users: InMemoryUserRepository
    tokens: FakeTokenService
    providers: dict[str, IdentityProvider]
    sign_in: SignInWithIdentity

    @property
    def start(self) -> StartSsoSignIn:
        return StartSsoSignIn(self.providers, self.store)

    @property
    def complete(self) -> CompleteSsoSignIn:
        return CompleteSsoSignIn(self.providers, self.store, self.sign_in)

    @property
    def redeem(self) -> RedeemSsoCode:
        return RedeemSsoCode(self.store, self.users, self.tokens)

    async def begin(self, provider: str = "fake") -> tuple[SsoSignInStart, str, str]:
        """Start, then let the fake provider 'approve': returns (start, state, code)."""
        started = await self.start.execute(provider=provider, redirect_uri=REDIRECT_URI)
        state, code = _state_and_code(started.authorization_url)
        return started, state, code

    async def finish(self, provider: str = "fake") -> str:
        started, state, code = await self.begin(provider)
        return await self.complete.execute(
            provider=provider,
            state=state,
            code=code,
            browser_binding=started.browser_binding,
            redirect_uri=REDIRECT_URI,
        )


def _state_and_code(url: str) -> tuple[str, str]:
    query = parse_qs(urlsplit(url).query)
    return query["state"][0], query.get("code", ["code-from-the-provider"])[0]


@pytest.fixture
def flow() -> Flow:
    clock = MutableClock()
    users = InMemoryUserRepository()
    return Flow(
        clock=clock,
        store=InMemoryOneTimeStore(clock),
        users=users,
        tokens=FakeTokenService(),
        providers={"fake": FakeIdentityProvider()},
        sign_in=SignInWithIdentity(users, InMemoryUserIdentityRepository(), clock=clock),
    )


async def test_the_whole_flow_ends_with_an_access_token_for_the_signed_in_user(
    flow: Flow,
) -> None:
    exchange_code = await flow.finish()

    token = await flow.redeem.execute(exchange_code)

    user = await flow.users.get_by_id(flow.tokens.decode(token))
    assert user is not None
    assert user.email == FakeIdentityProvider.DEMO_IDENTITY.email
    assert user.hashed_password is None


async def test_state_nonce_binding_and_exchange_code_are_long_random_and_never_repeat(
    flow: Flow,
) -> None:
    secrets_seen: set[str] = set()
    for _ in range(5):
        started, state, _ = await flow.begin()
        secrets_seen |= {state, started.browser_binding}
        secrets_seen.add(await flow.finish())

    assert len(secrets_seen) == 15
    assert all(len(secret) >= 32 for secret in secrets_seen)


async def test_no_secret_is_kept_as_a_store_key(flow: Flow) -> None:
    """Keys are digests: reading the store's key space reveals no usable state or code."""
    started, state, _ = await flow.begin()
    exchange_code = await flow.finish()

    for key in flow.store.stored_keys():
        for secret in (state, started.browser_binding, exchange_code):
            assert secret not in key


async def test_start_refuses_a_provider_that_is_not_enabled(flow: Flow) -> None:
    with pytest.raises(UnknownIdentityProviderError):
        await flow.start.execute(provider="google", redirect_uri=REDIRECT_URI)


async def test_complete_refuses_a_provider_that_is_not_enabled(flow: Flow) -> None:
    started, state, code = await flow.begin()

    with pytest.raises(UnknownIdentityProviderError):
        await flow.complete.execute(
            provider="google",
            state=state,
            code=code,
            browser_binding=started.browser_binding,
            redirect_uri=REDIRECT_URI,
        )


async def test_the_provider_receives_the_nonce_and_redirect_uri_of_this_flow(flow: Flow) -> None:
    stub = StubIdentityProvider("stub", an_identity(provider="stub"))
    flow.providers["stub"] = stub
    started = await flow.start.execute(provider="stub", redirect_uri=REDIRECT_URI)
    state, _ = _state_and_code(started.authorization_url)
    nonce = started.authorization_url.rpartition("nonce=")[2]

    await flow.complete.execute(
        provider="stub",
        state=state,
        code="the-code",
        browser_binding=started.browser_binding,
        redirect_uri=REDIRECT_URI,
    )

    assert stub.exchanges == [{"code": "the-code", "redirect_uri": REDIRECT_URI, "nonce": nonce}]


async def test_a_state_that_was_never_issued_is_refused(flow: Flow) -> None:
    started, state, code = await flow.begin()

    with pytest.raises(SsoStateInvalidError):
        await flow.complete.execute(
            provider="fake",
            state=state + "x",
            code=code,
            browser_binding=started.browser_binding,
            redirect_uri=REDIRECT_URI,
        )


async def test_a_state_works_once(flow: Flow) -> None:
    started, state, code = await flow.begin()
    arguments = {
        "provider": "fake",
        "state": state,
        "code": code,
        "browser_binding": started.browser_binding,
        "redirect_uri": REDIRECT_URI,
    }
    await flow.complete.execute(**arguments)

    with pytest.raises(SsoStateInvalidError):
        await flow.complete.execute(**arguments)


async def test_a_state_expires_within_minutes(flow: Flow) -> None:
    started, state, code = await flow.begin()
    assert timedelta(minutes=10) >= STATE_TTL
    flow.clock.advance(STATE_TTL)

    with pytest.raises(SsoStateInvalidError):
        await flow.complete.execute(
            provider="fake",
            state=state,
            code=code,
            browser_binding=started.browser_binding,
            redirect_uri=REDIRECT_URI,
        )


@pytest.mark.parametrize("binding", [None, "", "somebody-else's-browser"])
async def test_a_state_is_refused_in_a_browser_that_did_not_start_the_flow(
    flow: Flow, binding: str | None
) -> None:
    """Login CSRF: an attacker starts a flow and plants the callback URL in a victim's
    browser. The victim's browser does not hold the attacker's binding cookie."""
    _, state, code = await flow.begin()

    with pytest.raises(SsoStateInvalidError):
        await flow.complete.execute(
            provider="fake",
            state=state,
            code=code,
            browser_binding=binding,
            redirect_uri=REDIRECT_URI,
        )


async def test_a_refused_state_is_spent_too(flow: Flow) -> None:
    started, state, code = await flow.begin()
    with pytest.raises(SsoStateInvalidError):
        await flow.complete.execute(
            provider="fake",
            state=state,
            code=code,
            browser_binding="wrong",
            redirect_uri=REDIRECT_URI,
        )

    with pytest.raises(SsoStateInvalidError):
        await flow.complete.execute(
            provider="fake",
            state=state,
            code=code,
            browser_binding=started.browser_binding,
            redirect_uri=REDIRECT_URI,
        )


async def test_a_state_issued_for_one_provider_is_refused_at_another(flow: Flow) -> None:
    flow.providers["stub"] = StubIdentityProvider("stub", an_identity(provider="stub"))
    started, state, code = await flow.begin("fake")

    with pytest.raises(SsoStateInvalidError):
        await flow.complete.execute(
            provider="stub",
            state=state,
            code=code,
            browser_binding=started.browser_binding,
            redirect_uri=REDIRECT_URI,
        )


@pytest.mark.parametrize("missing", ["state", "code"])
async def test_a_callback_without_state_or_code_is_refused(flow: Flow, missing: str) -> None:
    """What the provider sends when the person declines: an ``error``, and no code."""
    started, state, code = await flow.begin()
    arguments: dict[str, str | None] = {"state": state, "code": code}
    arguments[missing] = None

    with pytest.raises(SsoStateInvalidError):
        await flow.complete.execute(
            provider="fake",
            browser_binding=started.browser_binding,
            redirect_uri=REDIRECT_URI,
            **arguments,
        )


@pytest.mark.parametrize(
    "error",
    [IdentityCodeRejectedError(), IdentityProviderUnavailableError()],
)
async def test_a_provider_failure_passes_through_and_issues_no_code(
    flow: Flow, error: Exception
) -> None:
    flow.providers["stub"] = StubIdentityProvider("stub", error)

    with pytest.raises(type(error)):
        await flow.finish("stub")

    assert flow.store.stored_keys() == []


async def test_an_unverified_email_issues_no_code(flow: Flow) -> None:
    unverified = an_identity(provider="stub", email_verified=False)
    flow.providers["stub"] = StubIdentityProvider("stub", unverified)

    with pytest.raises(EmailNotVerifiedError):
        await flow.finish("stub")

    assert flow.store.stored_keys() == []


async def test_an_inactive_user_issues_no_code(flow: Flow) -> None:
    inactive = a_user(is_active=False)
    await flow.users.add(inactive)
    flow.providers["stub"] = StubIdentityProvider(
        "stub", an_identity(provider="stub", email=inactive.email)
    )

    with pytest.raises(UserNotActiveError):
        await flow.finish("stub")

    assert flow.store.stored_keys() == []


async def test_an_identity_that_names_another_provider_is_refused(flow: Flow) -> None:
    """An adapter may only vouch for itself: (provider, subject) is the account key."""
    flow.providers["stub"] = StubIdentityProvider("stub", an_identity(provider="google"))

    with pytest.raises(IdentityCodeRejectedError):
        await flow.finish("stub")


async def test_an_exchange_code_works_once(flow: Flow) -> None:
    exchange_code = await flow.finish()
    await flow.redeem.execute(exchange_code)

    with pytest.raises(InvalidSsoCodeError):
        await flow.redeem.execute(exchange_code)


async def test_an_exchange_code_expires_within_about_a_minute(flow: Flow) -> None:
    exchange_code = await flow.finish()
    assert timedelta(seconds=90) >= EXCHANGE_CODE_TTL
    flow.clock.advance(EXCHANGE_CODE_TTL)

    with pytest.raises(InvalidSsoCodeError):
        await flow.redeem.execute(exchange_code)


@pytest.mark.parametrize("code", ["", "never-issued", "x" * 5000])
async def test_an_unknown_exchange_code_is_refused(flow: Flow, code: str) -> None:
    with pytest.raises(InvalidSsoCodeError):
        await flow.redeem.execute(code)


async def test_a_state_cannot_be_redeemed_as_an_exchange_code(flow: Flow) -> None:
    _, state, _ = await flow.begin()

    with pytest.raises(InvalidSsoCodeError):
        await flow.redeem.execute(state)


async def test_an_exchange_code_cannot_be_used_as_a_state(flow: Flow) -> None:
    exchange_code = await flow.finish()
    started, _, code = await flow.begin()

    with pytest.raises(SsoStateInvalidError):
        await flow.complete.execute(
            provider="fake",
            state=exchange_code,
            code=code,
            browser_binding=started.browser_binding,
            redirect_uri=REDIRECT_URI,
        )


async def test_a_user_deactivated_before_redeeming_gets_no_token(flow: Flow) -> None:
    exchange_code = await flow.finish()
    user = await flow.users.get_by_email(FakeIdentityProvider.DEMO_IDENTITY.email)
    assert user is not None
    flow.users._users[user.id] = dataclasses.replace(user, is_active=False)

    with pytest.raises(InvalidSsoCodeError):
        await flow.redeem.execute(exchange_code)
