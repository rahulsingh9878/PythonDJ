"""
HTTP REST endpoints.

All business logic lives in MusicService; these handlers are thin
request-parsing / response-shaping wrappers.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..core.config import settings
from ..core.state import app_state
from ..models.responses import (
    ChartsResponse,
    LyricsResponse,
    SuggestionsResponse,
    TrackLyricsResponse,
)
from ..services.music_service import music_service
from ..utils.helpers import detect_verses, generate_qr_base64

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# ---------------------------------------------------------------------------
# Startup event is now handled by the lifespan handler in app/main.py
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _template_context(request: Request, overrides: dict = None) -> dict:
    """
    Build the Jinja2 template context from current player state.

    Never mutates `app_state.player_context` directly – instead returns
    a *fresh copy* with `request` injected so the request object does not
    leak into the shared state between requests.
    """
    ctx = dict(app_state.player_context)
    ctx["request"] = request
    if "music_type" not in ctx:
        ctx["music_type"] = "songs"
    if overrides:
        ctx.update(overrides)
    return ctx


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def index_webview(request: Request):
    """Render the main music-player UI."""
    return templates.TemplateResponse("index.html", _template_context(request))


@router.post("/search/")
async def search_endpoint(
    request: Request,
    query: str = Form(..., examples=["MASAKALI"]),
    limit: int = Form(30, ge=1, le=50),
    nextPlay: bool = Form(False),
    maxVol: int = Form(100, ge=1, le=100),
    music_type: str = Form("songs"),
    videoId: Optional[str] = Form(None),
    refresh: bool = Form(False),
):
    """
    Search YouTube Music (songs + videos, parallel) and return results.

    - If `nextPlay=True` + `videoId` is set: triggers the smart-play+radio flow.
    - Otherwise performs a regular dual-category search.
    - Returns JSON when `Accept: application/json`, otherwise re-renders the UI.
    """
    logger.info(
        "Search query='%s' type=%s nextPlay=%s videoId=%s refresh=%s",
        query,
        music_type,
        nextPlay,
        videoId,
        refresh,
    )

    try:
        if nextPlay and videoId:
            context = await music_service.play_and_populate(
                video_id=videoId,
                title=query,
                limit=limit,
                maxVol=maxVol,
                music_type=music_type,
            )
        else:
            context = await music_service.perform_search(
                query=query,
                limit=limit,
                nextPlay=nextPlay,
                maxVol=maxVol,
                music_type=music_type,
                videoId=videoId,
                refresh=refresh,
            )
    except Exception as exc:
        logger.exception("Search failed for query='%s'", query)
        raise HTTPException(status_code=500, detail=str(exc))

    if request.headers.get("Accept") == "application/json":
        return JSONResponse(content=context)

    return templates.TemplateResponse(
        "index.html", _template_context(request, overrides=context)
    )


@router.get("/suggestions/", response_model=SuggestionsResponse)
def get_search_suggestions(query: str = Query(..., min_length=1)):
    """Return autocomplete suggestions for *query*."""
    suggestions = music_service.get_suggestions(query)
    return {"suggestions": suggestions}


@router.get("/lyrics/", response_model=LyricsResponse)
def get_lyrics_endpoint(
    title: str = Query(..., examples=["MASAKALI"]),
    artist: Optional[str] = Query(None),
):
    """
    Fetch lyrics directly (legacy endpoint).

    Tries YouTube Music first; falls back to RapidAPI / Musixmatch.
    Requires ``RAPIDAPI_KEY`` environment variable for the fallback.
    """
    if not settings.rapidapi_key:
        raise HTTPException(status_code=500, detail="RAPIDAPI_KEY is not configured")

    result = music_service.fetch_lyrics(title, artist, browseId=None, delay=0.5)

    if "error" in result:
        status = result.get("status", 500)
        raise HTTPException(status_code=status, detail=result["error"])

    return result


@router.get("/track/{idx}/", response_model=TrackLyricsResponse)
def get_track_lyrics_by_index(idx: int):
    """
    Return track metadata + lyrics for the track at *idx* in the current
    queue (`app_state.out_tracks`).  Also updates `app_state.next_song`
    with the first verse timestamp so the player knows when to cross-fade.
    """
    if idx < 0:
        raise HTTPException(status_code=400, detail="idx must be >= 0")

    if idx >= len(app_state.out_tracks):
        raise HTTPException(
            status_code=400,
            detail=f"idx {idx} out of range (0..{len(app_state.out_tracks) - 1})",
        )

    t = app_state.out_tracks[idx]
    title = t.get("title", "")
    artist = t.get("artist", "")
    video_id = t.get("videoId", "")

    selected = {
        "index": idx,
        "title": title,
        "artist": artist,
        "videoId": video_id,
        "music_url": (
            f"https://music.youtube.com/watch?v={video_id}" if video_id else ""
        ),
    }

    browse_id = t.get("browseId")
    lyrics_response = music_service.fetch_lyrics(title, artist, browseId=browse_id)

    verses = []
    lyrics_data = lyrics_response.get("data")

    if lyrics_data:
        if lyrics_response.get("source") == "YT":
            raw_text = lyrics_data.get("lyrics", "")
            for i, block in enumerate(raw_text.split("\n\n")):
                if block.strip():
                    verses.append(
                        {
                            "index": i,
                            "start_time": 0 if i == 0 else -1,
                            "end_time": -1,
                            "first_line": block.strip().split("\n")[0],
                            "text": block.strip(),
                        }
                    )
        else:
            verses = detect_verses(lyrics_data, gap_threshold=8.0)

    # Update next-song crossfade metadata
    app_state.next_song["title"] = title
    app_state.next_song["videoId"] = video_id
    app_state.next_song["timestamp"] = (
        int(verses[0]["start_time"])
        if verses and verses[0].get("start_time", -1) >= 0
        else 20
    )

    return {
        "selected_track": selected,
        "verse": verses,
        "source": lyrics_response.get("source", "Unknown"),
    }


@router.post("/radio/")
async def start_radio_mode(
    videoId: str = Form(...),
    limit: int = Form(50, ge=1, le=100),
):
    """Start radio mode seeded from *videoId*."""
    logger.info("Radio mode starting videoId=%s limit=%d", videoId, limit)
    try:
        return await music_service.start_radio(video_id=videoId, limit=limit)
    except Exception as exc:
        logger.exception("Radio failed for videoId=%s", videoId)
        raise HTTPException(status_code=500, detail=str(exc))


# Hardcoded failsafe tracks shown when the recommender hasn't warmed up yet
_FAILSAFE_TRACKS = [
    {"videoId": "k4yXQkGDbLY", "title": "Shape of You",  "artist": "Ed Sheeran"},
    {"videoId": "JGwWNGJdvx8", "title": "Despacito",     "artist": "Luis Fonsi"},
    {"videoId": "OPf0YbXqDm0", "title": "Uptown Funk",   "artist": "Mark Ronson"},
    {"videoId": "09R8_2nJtjg", "title": "Sugar",         "artist": "Maroon 5"},
]


@router.get("/charts/", response_model=ChartsResponse)
def get_charts(country: str = Query("IN", min_length=2, max_length=2)):
    """
    Return trending / chart tracks.

    Uses the AsyncIndianMusicRecommender playlist when the database has
    warmed up, otherwise falls back to a small set of hardcoded tracks.
    """
    logger.info("Charts request country=%s", country)

    try:
        playlist = music_service.recommender.generate_dynamic_playlist(50)
        if not playlist:
            raise ValueError("Recommender returned an empty playlist")

        formatted = [
            {
                "title": s["title"],
                "artist": s["artist"],
                "videoId": s["videoId"],
                "browseId": "",
                "music_url": s.get("music_url", ""),
                "thumbnail": s["thumbnail"],
                "type": "chart",
                "labels": [
                    "Trending",
                    s.get("category", "").capitalize(),
                ],
                "weight": 10,
            }
            for s in playlist
        ]

        return {
            "country": country,
            "top_songs": formatted[:25],
            "top_videos": [],
            "trending": formatted[25:],
        }

    except Exception as exc:
        logger.warning("Recommender not ready, using failsafe: %s", exc)

        failsafe = [
            {
                "title": t["title"],
                "artist": t["artist"],
                "videoId": t["videoId"],
                "browseId": "",
                "music_url": f"https://music.youtube.com/watch?v={t['videoId']}",
                "thumbnail": f"https://i.ytimg.com/vi/{t['videoId']}/hqdefault.jpg",
                "type": "chart",
                "labels": ["Hit"],
                "weight": 10,
            }
            for t in _FAILSAFE_TRACKS
        ]
        return {"country": country, "top_songs": failsafe, "top_videos": [], "trending": failsafe}


@router.get("/qr/")
async def get_qr_code(request: Request):
    """
    Generate a Base64-encoded QR code pointing to the server root.

    Controllers scan this to pair with the current player session.
    Respects `X-Forwarded-Host` / `X-Forwarded-Proto` headers set by
    reverse proxies (Nginx, Render, ngrok, etc.).
    """
    host = request.headers.get("x-forwarded-host", request.base_url.netloc)
    scheme = request.headers.get("x-forwarded-proto", "http")
    pairing_url = f"{scheme}://{host}/"
    logger.debug("QR pairing URL: %s", pairing_url)
    return JSONResponse(content=generate_qr_base64(pairing_url))
