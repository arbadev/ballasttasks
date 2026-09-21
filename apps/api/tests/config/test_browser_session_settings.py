import pytest
from pydantic import ValidationError
from starlette.responses import Response

from app.bootstrap import build_container, load_settings
from app.infrastructure.config.settings import CorsSettings


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://*.example.test",
        "https://web.test/path",
        "null",
        "http://web.test",
        "https://user:password@web.test",
        "https://web.test?x=1",
    ],
)
def test_cookie_origins_must_be_exact_https_or_loopback(origin: str) -> None:
    with pytest.raises(ValidationError):
        CorsSettings(allowed_origins=[origin])


@pytest.mark.parametrize("production", [False, True])
async def test_cookie_flags_follow_deployment_and_configured_jwt_lifetime(
    minimal_env: pytest.MonkeyPatch, production: bool
) -> None:
    minimal_env.setenv("APP__ENV", "production" if production else "development")
    minimal_env.setenv(
        "CORS__ALLOWED_ORIGINS",
        '["https://web.example.test"]' if production else '["http://127.0.0.1:3000"]',
    )
    minimal_env.setenv("AUTH__ACCESS_TOKEN_EXPIRE_MINUTES", "7")
    container = build_container(load_settings())
    try:
        response = Response()
        container.browser_session.issue(response, "synthetic-placeholder")
        cookie = response.headers["set-cookie"]
        assert "Max-Age=420" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie
        assert "Path=/" in cookie
        assert ("Secure" in cookie) is production
        assert "Domain=" not in cookie
        assert response.headers["cache-control"] == "no-store"
    finally:
        await container.aclose()
