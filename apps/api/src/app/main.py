"""ASGI entrypoint: ``uvicorn app.main:create_app --factory``."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_error_handlers
from app.api.routes import auth, health, sso, tasks
from app.bootstrap import Container, Settings, build_container, load_settings


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    """settings -> bootstrap -> routes. Tests inject a ``container`` of fakes."""
    if container is None:
        container = build_container(settings or load_settings())
    elif settings is not None and settings != container.settings:
        raise ValueError("settings and container.settings disagree; pass only one of them")
    settings = container.settings

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await container.aclose()

    app = FastAPI(
        title="Ballast Tasks API",
        version="0.1.0",
        debug=settings.app.debug,
        lifespan=lifespan,
    )
    app.state.container = container
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(sso.router)
    app.include_router(tasks.router)
    return app
