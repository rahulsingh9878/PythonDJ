"""
Application factory for the Premium Video DJ backend.

The `create_app()` factory wires together:
  - CORS middleware
  - API routers (HTTP + WebSocket)
  - Static-file mounting
  - Startup / shutdown lifecycle via the `lifespan` context manager

The module-level `app` object is what Uvicorn / Gunicorn import:

    uvicorn app.main:app
    gunicorn -k uvicorn.workers.UvicornWorker app.main:app
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import endpoints, websocket_routes, wled_routes
from .core.cache import create_cache, make_key
from .core.config import settings
from .core.logging import setup_logging
from .core.state import app_state
from .services.music_service import music_service
from .services.wled import catalog as wled_catalog
from .services.wled.controller import wled_controller


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Replaces the deprecated @app.on_event("startup") / ("shutdown") pattern.

    Everything *before* `yield` runs at startup; everything *after* runs at
    shutdown.
    """
    # --- Startup ---
    setup_logging(settings.log_level)

    cache = await create_cache(settings.redis_url)
    music_service.set_cache(cache)
    await wled_catalog.load(cache)

    # Restore player context + queue from the previous session (if available).
    saved_context = await cache.get(make_key("player", "context"))
    if saved_context:
        app_state.player_context.update(saved_context)
        tracks = saved_context.get("tracks", [])
        if tracks:
            app_state.out_tracks.extend(tracks)
            import logging
            logging.getLogger(__name__).info(
                "Player state restored from Redis – %d tracks in queue", len(tracks)
            )

    await music_service.initialize()
    yield

    # --- Shutdown ---
    await wled_controller.aclose()
    await cache.close()


def create_app() -> FastAPI:
    """Construct and return the configured FastAPI application."""
    app = FastAPI(
        title=settings.app_title,
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------
    # Middleware
    # ------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------
    app.include_router(endpoints.router, tags=["Music API"])
    app.include_router(websocket_routes.router, tags=["WebSocket"])
    app.include_router(wled_routes.router, tags=["WLED"])

    # ------------------------------------------------------------------
    # Static files
    # ------------------------------------------------------------------
    app.mount("/static", StaticFiles(directory="static"), name="static")

    return app


# Module-level instance consumed by the ASGI server
app = create_app()
