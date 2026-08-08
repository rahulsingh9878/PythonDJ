# Premium Video DJ — Backend

A real-time music DJ platform built with **FastAPI**. Search YouTube Music, generate smart radio playlists, sync multiple devices over WebSockets, and fetch lyrics — all optimised for Indian music discovery.

---

## What's inside

| Layer | Responsibility |
|---|---|
| `app/core/` | Config (Pydantic Settings), centralised logging, shared application state |
| `app/models/` | Pydantic request + response schemas for type-safe, self-documenting APIs |
| `app/api/` | HTTP endpoints, WebSocket hub, FastAPI dependency providers |
| `app/services/` | Business logic — music search/radio/lyrics, WebSocket connection pool, Indian music recommender |
| `app/utils/` | Pure utility functions (LRC parser, QR generator) |
| `templates/` | Jinja2 player UI |
| `static/` | JS sync client + CSS |

---

## Project Structure

```
.
├── app/
│   ├── main.py                     # App factory + lifespan (startup / shutdown)
│   ├── api/
│   │   ├── deps.py                 # FastAPI Depends() providers
│   │   ├── endpoints.py            # HTTP REST endpoints
│   │   └── websocket_routes.py     # WebSocket hub + dedicated routes
│   ├── core/
│   │   ├── config.py               # Pydantic BaseSettings (reads .env)
│   │   ├── logging.py              # Centralised logging setup
│   │   └── state.py                # AppState dataclass – single source of truth
│   ├── models/
│   │   ├── requests.py             # Validated request schemas
│   │   └── responses.py            # Typed response schemas
│   ├── services/
│   │   ├── music_service.py        # Search, radio, lyrics — single YTMusic session
│   │   ├── connection_manager.py   # WebSocket pool (player / controller roles)
│   │   └── recommender_system.py   # Async Indian music playlist builder
│   └── utils/
│       └── helpers.py              # LRC parser, QR generator
├── templates/
│   └── index.html                  # Jinja2 music player UI
├── static/
│   ├── js/index.js                 # DJSyncClient (WebSocket sync)
│   └── css/index.css
├── .env.example                    # Environment variable template
├── run.py                          # Local dev entry point
├── render.yaml                     # Render.com deployment config
└── requirements.txt                # Pinned dependencies
```

---

## Quick Start

**1. Copy the environment template**

```bash
cp .env.example .env
# Edit .env and set RAPIDAPI_KEY (required for lyrics fallback)
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

**3. Run locally**

```bash
python run.py
# → http://localhost:8045
# → API docs at http://localhost:8045/docs
```

---

## Configuration

All settings are defined in `app/core/config.py` using **Pydantic `BaseSettings`**.
They are read from environment variables or a `.env` file — no hardcoded secrets.

| Variable | Required | Default | Description |
|---|---|---|---|
| `RAPIDAPI_KEY` | Yes* | — | Musixmatch lyrics fallback (*not needed if YT lyrics always succeed) |
| `RAPIDAPI_HOST` | No | `spotify-web-api3.p.rapidapi.com` | RapidAPI host |
| `LOG_LEVEL` | No | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `HOST` | No | `0.0.0.0` | Bind address |
| `PORT` | No | `8045` | Bind port |
| `DEBUG` | No | `false` | Enable debug mode |

---

## API Reference

### HTTP Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | Jinja2 player UI |
| POST | `/search/` | Parallel song + video search; returns JSON or re-renders UI |
| GET | `/suggestions/` | Live autocomplete |
| GET | `/lyrics/` | Lyrics (YTMusic → RapidAPI fallback) |
| GET | `/track/{idx}/` | Track metadata + lyrics from the current queue |
| POST | `/radio/` | Start radio from a seed track |
| GET | `/charts/` | Trending Indian music playlist |
| GET | `/qr/` | Base64 QR code for device pairing |

Full interactive docs: **`/docs`** (Swagger UI) or **`/redoc`** (ReDoc).

### WebSocket Endpoints

| Path | Description |
|---|---|
| `/ws/sync?role=controller\|player` | **Primary** — unified sync hub |
| `/ws/play` | Dedicated play / search route |
| `/ws/radio` | Dedicated radio route |
| `/ws/`, `/ws/vol/`, `/ws/qr/`, `/ws/player/` | Legacy (deprecated, kept for compatibility) |

#### Sync Hub Message Format

```json
{ "type": "<action>", "data": { ... } }
```

| `type` | Direction | Description |
|---|---|---|
| `ping` | Client → Server | Heartbeat; player includes `currentTime`, `duration`, `videoId` |
| `pong` | Server → Client | Heartbeat response |
| `player_status` | Server → Controllers | Current playback position relayed from player |
| `play` | Controller → Server | Play a specific track + populate radio queue |
| `search` | Controller → Server | Global search; results broadcast to all controllers |
| `radio` | Controller → Server | Start radio mode |
| `suggest` | Controller → Server | Autocomplete; response sent back to requester only |
| `vol` | Any → Server | Volume change; synced to all other clients |
| `mute` | Any → Server | Mute toggle; synced to all other clients |
| `control` | Any → Server | Play / Pause / Next / Prev; broadcast to all |
| `qr` | Controller → Server | Generate QR for a URL; response sent to requester only |
| `search_result` | Server → Controllers | Search / play results |
| `radio_result` | Server → Controllers | Radio playlist results |

---

## Architecture Notes

### Application State (`app/core/state.py`)

A single `AppState` dataclass instance (`app_state`) is the **only** place mutable runtime state lives.
All modules import and mutate this one object — no scattered module-level globals.

```python
from app.core.state import app_state

app_state.out_tracks          # current track queue
app_state.player_context      # volume, mute, music_type, last search context
app_state.next_song           # title / videoId / crossfade timestamp
```

### Configuration (`app/core/config.py`)

`Settings` inherits from Pydantic `BaseSettings`.
Values cascade: **env vars > `.env` file > field defaults**.
Import the singleton anywhere:

```python
from app.core.config import settings
settings.rapidapi_key
settings.cors_origins
```

### Dependency Injection (`app/api/deps.py`)

FastAPI `Depends()` providers are centralised here so route handlers stay thin and testable:

```python
from app.api.deps import get_music_service

@router.get("/foo")
async def foo(svc: MusicService = Depends(get_music_service)):
    ...
```

### Logging (`app/core/logging.py`)

`setup_logging()` is called once in the lifespan handler.
Every module creates its own named logger:

```python
import logging
logger = logging.getLogger(__name__)
```

### Music Service (`app/services/music_service.py`)

- One `YTMusic` session shared with the recommender (no duplicate auth).
- `_best_thumbnail()` and `_clean_suggestions()` are module-level helpers — no duplication between search and radio paths.
- `fetch_lyrics` is a sync method (safe — FastAPI runs sync endpoints in a thread pool).
- `perform_search` and `start_radio` are async and use `ThreadPoolExecutor` for the blocking ytmusicapi calls.

### Indian Music Recommender (`app/services/recommender_system.py`)

Builds a genre-balanced database at startup using `asyncio.gather` over a thread pool.
`generate_dynamic_playlist(n)` samples from the database respecting the distribution below.

| Genre | Share |
|---|---|
| Bollywood 2000–2025 (3 eras) | 65 % |
| Punjabi | 15 % |
| Indie / Regional | 15 % |
| Haryanvi | 5 % |

---

## Production Deployment

**Render.com** (configured via `render.yaml`):

```
Build:  pip install -r requirements.txt
Start:  gunicorn -k uvicorn.workers.UvicornWorker app.main:app --bind 0.0.0.0:$PORT
```

**Any ASGI host:**

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

Set `RAPIDAPI_KEY` (and optionally `RAPIDAPI_HOST`) as environment variables on the host platform.

---

## Key Changes vs. v1

| Area | Before | After |
|---|---|---|
| Configuration | Bare `os.environ.get` | Pydantic `BaseSettings` with validation + `.env` support |
| State | Module-level mutable globals | `AppState` dataclass singleton |
| Startup hook | Deprecated `@router.on_event` | `lifespan` context manager |
| Logging | `print()` everywhere | `logging.getLogger(__name__)` per module |
| Request context | `default_context["request"] = request` leaked across requests | Fresh copy per request via `_template_context()` |
| Suggestions logic | Duplicated in HTTP + WS handlers | Single `_clean_suggestions()` in `MusicService` |
| Thumbnails | Duplicated resolution logic in search + radio | Single `_best_thumbnail()` helper |
| YTMusic sessions | Two instances (service + recommender) | One shared instance |
| `requirements.txt` | Unpinned, missing `qrcode` | All versions pinned, `qrcode[pil]` + `httpx` + `pydantic-settings` added |
| Legacy WS errors | Bare `except: pass` | Named `except Exception` with `logger.warning` |
| Root `utils.py` | Duplicate of `app/utils/helpers.py` | Deleted |
| Response types | Untyped dicts | Pydantic `BaseModel` response schemas |
| API docs | None | Auto-generated at `/docs` and `/redoc` |
