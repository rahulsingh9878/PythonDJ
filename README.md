# Premium Video DJ — Backend

A real-time music DJ platform built with **FastAPI**. Search YouTube Music, generate smart radio playlists, sync multiple devices over WebSockets, and fetch lyrics — all optimized for Indian music discovery.

---

## Features

- **Dual-Category Search** — Searches songs and videos in parallel, ranks results by label (Official, Remix, Live, Cover, Slowed)
- **Radio Mode** — Seeds a playlist from any track using both its audio and video IDs, fetching related tracks in parallel
- **Indian Music Recommender** — Pre-built background playlist generator (Bollywood, Punjabi, Haryanvi, Indie/Regional)
- **Cross-Device Sync** — WebSocket-based sync between a player device and one or more controller devices; pair via QR code
- **Lyrics Engine** — Fetches lyrics from YouTube Music first, falls back to Musixmatch via RapidAPI
- **Search Suggestions** — Live autocomplete as you type
- **Trending Charts** — Pulls region-specific (IN) trending tracks on demand

---

## Project Structure

```
.
├── app/
│   ├── main.py                     # FastAPI app setup, middleware, router registration
│   ├── api/
│   │   ├── endpoints.py            # HTTP REST endpoints
│   │   └── websocket_routes.py     # WebSocket handlers (sync, play, radio, volume, QR)
│   ├── core/
│   │   ├── config.py               # Environment config (API keys, CORS origins)
│   │   └── state.py                # Global in-memory state (queue, cache, player context)
│   ├── services/
│   │   ├── music_service.py        # Search, radio, lyrics logic via ytmusicapi
│   │   ├── connection_manager.py   # WebSocket connection pool (player vs controller roles)
│   │   └── recommender_system.py   # Async Indian music playlist builder
│   └── utils/
│       └── helpers.py              # LRC timestamp parser, QR code generator
├── templates/
│   └── index.html                  # Jinja2 music player UI
├── static/
│   ├── js/index.js                 # Frontend WebSocket sync client (DJSyncClient)
│   └── css/index.css               # Styles
├── run.py                          # Local dev entry point
├── render.yaml                     # Render.com deployment config
└── requirements.txt
```

---

## API Endpoints

### HTTP

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | Serve the Jinja2 player UI |
| POST | `/search/` | Search YouTube Music (songs + videos, parallel) |
| GET | `/suggestions/` | Live search autocomplete |
| GET | `/lyrics/` | Fetch lyrics (YTMusic → RapidAPI fallback) |
| GET | `/track/{idx}/` | Get lyrics for a queued track by index |
| POST | `/radio/` | Start radio from a track (dual-stream playlist) |
| GET | `/charts/` | Fetch trending Indian music charts |
| GET | `/qr/` | Generate a Base64 QR code for device pairing |

### WebSocket

| Route | Description |
|-------|-------------|
| `/ws/sync?role=controller\|player` | Unified sync hub (primary) |
| `/ws/play` | Dedicated play route |
| `/ws/radio` | Dedicated radio route |
| `/ws/`, `/ws/vol/`, `/ws/player/`, `/ws/qr/` | Legacy routes |

#### Message Types (Unified Sync)

```json
{ "type": "play|vol|control|search|radio|suggest|qr|ping", "data": {} }
```

---

## WebSocket Device Roles

Two device roles connect to `/ws/sync`:

- **`controller`** — Remote (phone/browser): sends search, play, volume, radio commands
- **`player`** — Display/speaker device: receives and executes commands

The server routes messages between roles using dedicated broadcaster classes (`PlayerBroadcaster`, `WebAppBroadcaster`). Pairing is done by scanning a QR code that points the second device to the server root.

---

## Music Search & Ranking

Search results are processed with a label detection + weight system:

| Label | Effect |
|-------|--------|
| Official | +10 weight (sorted first) |
| Remix / Live / Slowed / Cover / Lyrics | Flagged, deprioritized |

Results are ordered: **Official tracks → query matches → randomized rest**, with the currently playing track excluded.

---

## Indian Music Recommender

On startup, `AsyncIndianMusicRecommender` builds a background playlist (50 songs) with the following distribution:

| Genre | Share |
|-------|-------|
| Bollywood (2000–2009) | ~20% |
| Bollywood (2010–2019) | ~25% |
| Bollywood (2020–2025) | ~20% |
| Punjabi | 15% |
| Indie / Regional | 15% |
| Haryanvi | 5% |

Collections are fetched in parallel using `asyncio.gather`. The final playlist is shuffled before serving via `/charts/`.

---

## Local Development

**1. Install dependencies**

```bash
pip install -r requirements.txt
```

**2. Set environment variables**

```bash
export RAPIDAPI_KEY=your_key_here
# Optional:
export RAPIDAPI_HOST=spotify-web-api3.p.rapidapi.com
```

**3. Run the dev server**

```bash
python run.py
# Server starts at http://localhost:8045
```

---

## Production Deployment

**Render.com** (configured via `render.yaml`):

- **Build command:** `pip install -r requirements.txt`
- **Start command:** `gunicorn -k uvicorn.workers.UvicornWorker app.main:app --bind 0.0.0.0:$PORT`

**Manual / Docker:**

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Required environment variables:**

| Variable | Required | Default |
|----------|----------|---------|
| `RAPIDAPI_KEY` | Yes | — |
| `RAPIDAPI_HOST` | No | `spotify-web-api3.p.rapidapi.com` |

---

## Notes

- **State is global** — all connected clients share a single track queue (`out_tracks`). There is no per-user session isolation.
- **No database** — everything is computed on-demand and cached in memory.
- **Startup time** — the first run may take a few seconds while the recommender builds its collections in the background.
- **ytmusicapi** — uses an unofficial YouTube Music API wrapper; no API key required for search/radio.
- **CORS** — whitelisted for `localhost`, `127.0.0.1`, `0.0.0.0:5500`, and `rahulsingh9878.github.io`.
