"""Single sign-on over HTTP: start -> (provider) -> callback -> (web app) -> exchange.

Two rules hold for every line below:

- a browser is only ever redirected to the provider's authorization URL or to the web
  app's configured callback URL (``SsoConfig``, from settings). No query parameter, header
  or ``Host`` takes part in building a redirect target, so there is no open redirect;
- the access token never travels in a URL. The callback hands the web app a one-time code;
  ``POST /auth/sso/exchange`` swaps it for the token in a response body.

Every failure of the callback is the same redirect, ``<web callback>?error=sso_failed``
(``provider_unavailable`` when the provider could not be reached, so the screen can offer
"try again"): it says nothing about which check failed. Reasons are logged by error class
only; no state, code, cookie, token or email is ever logged.
"""

import logging
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.dependencies import (
    CompleteSsoSignInDep,
    IdentityProvidersDep,
    RedeemSsoCodeDep,
    SsoConfigDep,
    StartSsoSignInDep,
)
from app.api.schemas.auth import TokenResponse
from app.api.schemas.errors import ErrorResponse
from app.api.schemas.sso import SsoExchangeRequest, SsoProvider, SsoProvidersResponse
from app.api.security import unauthorized
from app.application.errors import (
    AuthenticationError,
    IdentityProviderUnavailableError,
    InvalidSsoCodeError,
    SsoError,
    UnknownIdentityProviderError,
)
from app.application.sso import MAX_SECRET_LENGTH, STATE_TTL, SsoConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/sso", tags=["auth"])

BINDING_COOKIE = "sso_binding"
# The cookie is sent to the start and callback routes and to nothing else.
BINDING_COOKIE_PATH = "/auth/sso"
CALLBACK_ROUTE = "sso_callback"

REDIRECT = {
    "headers": {"Location": {"schema": {"type": "string", "format": "uri"}}},
}
UNKNOWN_PROVIDER = {
    "model": ErrorResponse,
    "description": "No such provider is enabled (unknown and disabled are one answer)",
}

CallbackParameter = Annotated[str | None, Query(max_length=MAX_SECRET_LENGTH * 4)]


def _unknown_provider() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown single sign-on provider")


def _redirect(url: str) -> RedirectResponse:
    response = RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
    # The URLs of this flow carry one-time secrets: keep them out of caches and Referers.
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _provider_redirect_uri(request: Request, config: SsoConfig, provider: str) -> str:
    """The callback URL registered at the provider: the configured public base URL plus this
    application's own route path. The request contributes nothing."""
    path = request.app.url_path_for(CALLBACK_ROUTE, provider=provider)
    return f"{config.api_public_base_url}{path}"


@router.get(
    "/providers",
    response_model=SsoProvidersResponse,
    summary="The identity providers the login screen can offer",
)
async def providers(identity_providers: IdentityProvidersDep) -> SsoProvidersResponse:
    return SsoProvidersResponse(providers=[SsoProvider(name=name) for name in identity_providers])


@router.get(
    "/{provider}/start",
    status_code=status.HTTP_303_SEE_OTHER,
    response_class=RedirectResponse,
    summary="Begin a sign-in: redirect the browser to the identity provider",
    description=(
        "Navigate the browser here (a link, not `fetch`). Creates the state and nonce of "
        "this sign-in, remembers them server-side for a few minutes, binds them to this "
        "browser with an HttpOnly, SameSite=Lax cookie, and redirects to the provider."
    ),
    responses={
        status.HTTP_303_SEE_OTHER: {**REDIRECT, "description": "To the provider's sign-in page"},
        status.HTTP_404_NOT_FOUND: UNKNOWN_PROVIDER,
    },
)
async def start(
    provider: str, request: Request, start_sso_sign_in: StartSsoSignInDep, config: SsoConfigDep
) -> Response:
    try:
        started = await start_sso_sign_in.execute(
            provider=provider, redirect_uri=_provider_redirect_uri(request, config, provider)
        )
    except UnknownIdentityProviderError:
        raise _unknown_provider() from None
    except IdentityProviderUnavailableError:
        logger.warning("single sign-on start failed: provider unavailable")
        return _redirect(_failure_url(config, "provider_unavailable"))
    response = _redirect(started.authorization_url)
    response.set_cookie(
        BINDING_COOKIE,
        started.browser_binding,
        max_age=int(STATE_TTL.total_seconds()),
        path=BINDING_COOKIE_PATH,
        secure=config.cookies_are_secure,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get(
    "/{provider}/callback",
    name=CALLBACK_ROUTE,
    status_code=status.HTTP_303_SEE_OTHER,
    response_class=RedirectResponse,
    summary="Where the identity provider sends the browser back",
    description=(
        "Validates the state (single use, this browser, this provider), exchanges the "
        "provider's `code`, finds or creates the user, then redirects to the web app's "
        "configured callback URL with `?code=<one-time code>`, or with `?error=sso_failed` "
        "/ `?error=provider_unavailable`. The access token is never put in a URL."
    ),
    responses={
        status.HTTP_303_SEE_OTHER: {**REDIRECT, "description": "To the web app's callback URL"},
        status.HTTP_404_NOT_FOUND: UNKNOWN_PROVIDER,
    },
)
async def callback(
    provider: str,
    request: Request,
    complete_sso_sign_in: CompleteSsoSignInDep,
    config: SsoConfigDep,
    code: CallbackParameter = None,
    state: CallbackParameter = None,
    error: CallbackParameter = None,
    binding: Annotated[str | None, Cookie(alias=BINDING_COOKIE, include_in_schema=False)] = None,
) -> Response:
    try:
        exchange_code = await complete_sso_sign_in.execute(
            provider=provider,
            state=state,
            # The provider reports a refusal (``error=access_denied``) instead of a code; a
            # callback that carries both is no approval either. The state is spent anyway.
            code=None if error else code,
            browser_binding=binding,
            redirect_uri=_provider_redirect_uri(request, config, provider),
        )
    except UnknownIdentityProviderError:
        raise _unknown_provider() from None
    except IdentityProviderUnavailableError:
        logger.warning("single sign-on callback failed: provider unavailable")
        response = _redirect(_failure_url(config, "provider_unavailable"))
    except (SsoError, AuthenticationError) as error:
        logger.info("single sign-on callback failed: %s", type(error).__name__)
        response = _redirect(_failure_url(config, "sso_failed"))
    else:
        response = _redirect(f"{config.web_callback_url}?{urlencode({'code': exchange_code})}")
    # Spent either way, like the state it was bound to.
    response.delete_cookie(
        BINDING_COOKIE,
        path=BINDING_COOKIE_PATH,
        secure=config.cookies_are_secure,
        httponly=True,
        samesite="lax",
    )
    return response


def _failure_url(config: SsoConfig, error: str) -> str:
    return f"{config.web_callback_url}?{urlencode({'error': error})}"


@router.post(
    "/exchange",
    response_model=TokenResponse,
    summary="Swap the one-time code for an access token",
    description=(
        "The same body as `POST /auth/login`. The code works once and for about a minute; "
        "every failure, whatever its cause, is the same 401."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Unknown, already used or expired code",
            "headers": {"WWW-Authenticate": {"schema": {"type": "string", "const": "Bearer"}}},
        }
    },
)
async def exchange(
    body: SsoExchangeRequest, response: Response, redeem_sso_code: RedeemSsoCodeDep
) -> TokenResponse:
    try:
        token = await redeem_sso_code.execute(body.code)
    except InvalidSsoCodeError:
        raise unauthorized("Invalid or expired code") from None
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(access_token=token)
