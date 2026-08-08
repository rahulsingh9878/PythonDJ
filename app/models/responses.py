"""
Pydantic response models.

Annotating endpoint return types with these models:
  * Documents the API in the auto-generated OpenAPI / Swagger UI.
  * Catches accidental field name typos at runtime.
  * Makes it trivial to write unit tests against a known schema.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class TrackItem(BaseModel):
    """A single music track as returned by search / radio / charts."""

    title: str
    artist: str
    videoId: str
    music_url: str
    thumbnail: str
    type: str  # "song" | "video" | "chart" | …
    labels: List[str] = []
    weight: int = 0
    index: Optional[int] = None
    browseId: Optional[str] = None
    category: Optional[str] = None


class SearchResponse(BaseModel):
    """Returned by POST /search/ when the client sends Accept: application/json."""

    query: str
    tracks: List[TrackItem]
    video_tracks: List[TrackItem]
    song_tracks: List[TrackItem]
    recLimit: int
    maxVol: int
    music_type: str


class LyricsResponse(BaseModel):
    """Returned by GET /lyrics/ and GET /track/{idx}/"""

    status: int
    data: Optional[Any] = None
    source: Optional[str] = None
    error: Optional[str] = None


class TrackLyricsResponse(BaseModel):
    selected_track: Dict[str, Any]
    verse: List[Dict[str, Any]]
    source: str


class ChartsResponse(BaseModel):
    country: str
    top_songs: List[Dict[str, Any]]
    top_videos: List[Dict[str, Any]]
    trending: List[Dict[str, Any]]


class SuggestionsResponse(BaseModel):
    suggestions: List[str]
