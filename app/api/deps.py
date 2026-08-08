"""
FastAPI dependency providers.

Import and inject these with `Depends()` inside route handlers to keep
business-object creation and lifecycle management out of route code.

Example::

    @router.get("/search/")
    async def search(svc: MusicService = Depends(get_music_service)):
        ...
"""

from ..core.state import app_state, AppState
from ..services.music_service import music_service, MusicService
from ..services.connection_manager import (
    manager,
    player_broadcaster,
    webapp_broadcaster,
    DJConnectionManager,
    PlayerBroadcaster,
    WebAppBroadcaster,
)


def get_app_state() -> AppState:
    """Return the single shared application state instance."""
    return app_state


def get_music_service() -> MusicService:
    """Return the single shared MusicService instance."""
    return music_service


def get_connection_manager() -> DJConnectionManager:
    """Return the single shared DJConnectionManager instance."""
    return manager


def get_player_broadcaster() -> PlayerBroadcaster:
    return player_broadcaster


def get_webapp_broadcaster() -> WebAppBroadcaster:
    return webapp_broadcaster
