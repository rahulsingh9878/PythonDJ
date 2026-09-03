"""
Application configuration loaded from environment variables / .env file.

Usage anywhere in the app:
    from app.core.config import settings
    settings.rapidapi_key
"""

from typing import List
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Silently ignore unknown env vars
    )

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    app_title: str = "Premium Video DJ"
    app_version: str = "2.0.0"
    debug: bool = False
    log_level: str = "INFO"

    # ------------------------------------------------------------------
    # Server
    # ------------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8045

    # ------------------------------------------------------------------
    # Lyrics API  (RapidAPI / Musixmatch)
    # ------------------------------------------------------------------
    rapidapi_key: str = ""
    rapidapi_host: str = "spotify-web-api3.p.rapidapi.com"

    @computed_field  # type: ignore[misc]
    @property
    def rapidapi_url(self) -> str:
        return (
            f"https://{self.rapidapi_host}"
            "/v1/social/spotify/musixmatchsearchlyrics"
        )

    # ------------------------------------------------------------------
    # Redis cache
    # ------------------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    redis_heatmap_ttl: int = 8640000   # 24 hours  — heatmap rarely changes
    redis_radio_ttl: int = 180000      # 30 minutes — recommendations drift slowly
    redis_search_ttl: int = 60000      # 10 minutes — search results are fresher
    redis_suggestions_ttl: int = 300000 # 5 minutes  — autocomplete suggestions
    redis_recommender_ttl: int = 2160000  # 6 hours — avoids 40+ API calls on restart
    redis_player_ttl: int = 3600     # 1 hour   — queue / context restore after restart

    # ------------------------------------------------------------------
    # WLED (optional) — club-light ambience driven by the YouTube heatmap
    # ------------------------------------------------------------------
    wled_ip: str = "192.168.1.12"            # e.g. "192.168.1.12" — empty disables the feature
    wled_sx_min: int = 40
    wled_sx_max: int = 255
    wled_gamma: float = 1.0      # >1 compresses the low end, <1 expands it
    wled_rate: float = 1.0       # seconds between updates
    wled_deadband: int = 15      # skip the request if a param moved less than this (visible jump)
    # Peak-triggered effect/palette/color rotation reuses music_service's own
    # heatmap peak detection (min_value/min_gap_seconds/window there) — no
    # separate threshold setting needed here.

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------
    cors_origins: List[str] = [
        "https://rahulsingh9878.github.io",
        "http://localhost",
        "http://127.0.0.1",
        "http://0.0.0.0:5500",
        "http://localhost:5500",
    ]


# Single shared instance – import this everywhere
settings = Settings()

# ---------------------------------------------------------------------------
# Backward-compatible aliases so existing `from ..core.config import X` calls
# continue to work without changes across the codebase.
# ---------------------------------------------------------------------------
RAPIDAPI_KEY = settings.rapidapi_key
RAPIDAPI_HOST = settings.rapidapi_host
RAPIDAPI_URL = settings.rapidapi_url
ORIGINS = settings.cors_origins
