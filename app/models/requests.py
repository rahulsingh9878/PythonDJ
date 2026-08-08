"""
Pydantic request models.

These are used as FastAPI Form / Body / Query dependencies to give every
incoming payload clear validation, documentation, and type safety.
"""

from typing import Optional
from pydantic import BaseModel, Field


class SearchFormData(BaseModel):
    """Payload for POST /search/"""

    query: str = Field(..., min_length=1, examples=["MASAKALI"])
    limit: int = Field(30, ge=1, le=50)
    nextPlay: bool = False
    maxVol: int = Field(100, ge=1, le=100)
    music_type: str = Field("songs", pattern="^(songs|videos)$")
    videoId: Optional[str] = None
    refresh: bool = False


class RadioFormData(BaseModel):
    """Payload for POST /radio/"""

    videoId: str = Field(..., min_length=1)
    limit: int = Field(50, ge=1, le=100)


class WSSyncMessage(BaseModel):
    """
    Envelope for every message sent over the /ws/sync WebSocket.

    Example::

        {"type": "play", "data": {"videoId": "abc123", "title": "Song"}}
    """

    type: str
    data: Optional[dict] = None
