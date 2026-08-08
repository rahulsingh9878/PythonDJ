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
