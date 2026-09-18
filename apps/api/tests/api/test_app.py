import httpx
import pytest

from app.bootstrap import load_settings
from app.main import create_app


async def test_cors_allows_the_configured_origin_only(client: httpx.AsyncClient) -> None:
    allowed = await client.get("/health", headers={"Origin": "http://localhost:3000"})
    denied = await client.get("/health", headers={"Origin": "http://evil.example"})

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in denied.headers


async def test_create_app_builds_its_own_container_from_settings(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    app = create_app(settings=load_settings())

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client,
    ):
        assert (await client.get("/health")).json() == {"status": "ok"}
        assert app.state.container.settings.ai.provider == "fake"


def test_create_app_fails_fast_without_configuration(clean_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="database"):
        create_app()


def test_create_app_rejects_settings_that_disagree_with_the_container(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import build_container

    container = build_container(load_settings())
    minimal_env.setenv("AI__MODEL", "fake-2")

    with pytest.raises(ValueError, match="settings"):
        create_app(settings=load_settings(), container=container)
