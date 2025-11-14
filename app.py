# app.py
import os
import time
import requests
from typing import Optional, List

from fastapi import FastAPI, Query, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from ytmusicapi import YTMusic
from utils import detect_verses, find_video_id
from fastapi.templating import Jinja2Templates


app = FastAPI(title="YTMusic -> Lyrics FastAPI (no forward refs)", version="1.0")
origins = [
    "https://rahulsingh9878.github.io",
    "https://www.codechef.com/html-online-compiler",
    "http://localhost", # (Optional) Also allow your local computer for testing
    "http://127.0.0.1", # (Optional)
    "http://0.0.0.0:5500",
    "http://localhost:5500"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Configuration ----------
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")
RAPIDAPI_HOST = os.environ.get("RAPIDAPI_HOST", "spotify-web-api3.p.rapidapi.com")
RAPIDAPI_URL = f"https://{RAPIDAPI_HOST}/v1/social/spotify/musixmatchsearchlyrics"

# Initialize YTMusic (anonymous). Keep a single instance.
yt = YTMusic()

out_tracks = []
next_song_dt = {"title": None, "videoId": None, "timestamp": 20}
templates = Jinja2Templates(directory="templates")

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.vol_control_connections: List[WebSocket] = []  # Separate list for volume control

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    async def connect_vol_control(self, websocket: WebSocket):
        await websocket.accept()
        self.vol_control_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    def disconnect_vol_control(self, websocket: WebSocket):
        if websocket in self.vol_control_connections:
            self.vol_control_connections.remove(websocket)

    async def broadcast_json(self, message: dict):
        # iterate copy to avoid mutation issues
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                # If send fails, remove connection
                try:
                    await connection.close()
                except Exception:
                    pass
                self.disconnect(connection)

    async def broadcast_vol_control(self, message: dict):
        # Broadcast to volume control connections
        for connection in list(self.vol_control_connections):
            try:
                await connection.send_json(message)
            except Exception:
                # If send fails, remove connection
                try:
                    await connection.close()
                except Exception:
                    pass
                self.disconnect_vol_control(connection)

manager = ConnectionManager()

@app.websocket("/ws/")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket clients should connect here (ws://host:port/ws/).
    They will receive JSON messages like {"video_id": "abc123"} when /play/ is POSTed.
    """
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive. We don't expect messages from clients,
            # but we can receive pings or optional messages.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
        try:
            await websocket.close()
        except Exception:
            pass

@app.websocket("/ws/vol/")
async def websocket_vol_endpoint(websocket: WebSocket):
    """
    WebSocket clients send volume data here (ws://host:port/ws/vol/).
    Received messages are broadcasted to /ws/ctrlvol/ connections.
    """
    await manager.connect_vol_control(websocket)
    try:
        while True:
            # Receive volume data from client
            vol = await websocket.receive_text()
            # Broadcast the volume data to all /ws/ctrlvol/ connections
            try:
                vol_data = {"volume": vol}
                await manager.broadcast_vol_control(vol_data)
            except Exception as e:
                print(f"Error broadcasting volume: {e}")
            
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"Error in /ws/vol/: {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/recommendations/", response_class=HTMLResponse)
async def get_recommendations_as_webview(request: Request,
                        query: str = Query(..., example="MASAKALI"), 
                        limit: int = Query(10, ge=1, le=50),
                        nextPlay: bool = False):
    """
    Search a song on YouTube Music (by query) and return top recommendations (default limit 10).
    Returns a plain JSON dict to avoid Pydantic forward-ref issues.
    """
    global out_tracks
    try:
        if nextPlay and out_tracks:
            nextID = find_video_id(out_tracks, query)
            next_song_dt["videoId"] = nextID if nextID else next_song_dt["videoId"]
            next_song_dt["title"] = query
            await manager.broadcast_json(next_song_dt)
        search_results = yt.search(query, filter="songs", limit=1)
        if not search_results:
            raise HTTPException(status_code=404, detail="No search results found on YouTube Music")

        top_song = search_results[0]
        top_video_id = top_song.get("videoId")
        if not top_video_id:
            raise HTTPException(status_code=404, detail="Top search result has no videoId")

        recs = yt.get_watch_playlist(videoId=top_video_id)
        tracks = recs.get("tracks", [])[:limit]
        # print(tracks)
        out_tracks = []
        for idx, t in enumerate(tracks):
            title = t.get("title", "")
            artists = t.get("artists", [])
            thumbnail = t.get("thumbnail", [])[0]["url"]
            artist_name = artists[0]["name"] if artists else "Unknown Artist"
            video_id = t.get("videoId", "")
            url = f"https://music.youtube.com/watch?v={video_id}" if video_id else ""
            out_tracks.append({
                "index": idx,
                "title": title,
                "artist": artist_name,
                "videoId": video_id,
                "music_url": url, 
                "thumbnail": thumbnail,
            })

        # return {"query": query, "tracks": out_tracks}
        # if nextPlay:
        #     next_song_dt["videoId"] = out_tracks[0]['videoId']
        context = {
            "request": request,
            "query": query,
            "tracks": out_tracks
        }

        return templates.TemplateResponse("recommendations.html", context)

    except requests.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Upstream HTTP error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/lyrics/")
def get_lyrics(title: str = Query(..., example="MASAKALI"), artist: Optional[str] = Query(None, example="A. R. Rahman")):
    """
    Query RapidAPI endpoint that wraps Musixmatch-like search.
    Returns the raw payload (dict) from RapidAPI to avoid model parsing errors.
    """
    if not RAPIDAPI_KEY:
        raise HTTPException(status_code=500, detail="Missing RAPIDAPI_KEY environment variable")

    params = {"terms": title}
    if artist:
        params["artist"] = artist

    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST
    }

    # Short sleep to be gentle on upstream
    time.sleep(0.5)

    resp = requests.get(RAPIDAPI_URL, headers=headers, params=params, timeout=15)
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"RapidAPI HTTP error: {e} - {resp.text[:500]}")

    data = resp.json()
    # forward the status/data shape as-is
    return {"status": data.get("status", resp.status_code), "data": data.get("data", data)}


def fetch_lyrics(title: str, artist: str = None, delay: float = 0.5) -> dict:
    """
    Fetch lyrics using the RapidAPI Musixmatch wrapper.

    Args:
        title (str): Song title to search for
        artist (str, optional): Artist name (recommended for accuracy)
        delay (float, optional): Sleep time before request to avoid rate-limit issues

    Returns:
        dict: {
            "status": int,
            "data": dict (raw RapidAPI response)
        }

    Raises:
        HTTPException: If API key missing or HTTP errors occur
    """

    if not RAPIDAPI_KEY:
        raise HTTPException(status_code=500, detail="Missing RAPIDAPI_KEY environment variable")

    params = {"terms": title}
    if artist:
        params["artist"] = artist

    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST
    }

    # Prevent hammering upstream API
    time.sleep(delay)

    try:
        resp = requests.get(RAPIDAPI_URL, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return {"status": data.get("status", resp.status_code), "data": data.get("data", data)}
    except requests.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"RapidAPI HTTP error: {e} - {resp.text[:500]}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

@app.get("/track/{idx}/")
def get_track_lyrics_by_index(
    idx: int
):
    global out_tracks
    global next_song_dt
    """
    Fetch recommendations for `query`, select track at index `idx` (0-based),
    then call the lyrics RapidAPI endpoint for that track and return combined result.
    """
    if idx < 0:
        raise HTTPException(status_code=400, detail="idx must be >= 0")

    # Step 1: get recommendations (reuse the logic above)
    try:
        # find top search result
        if idx >= len(out_tracks):
            raise HTTPException(status_code=400, detail=f"idx {idx} out of range (0..{len(out_tracks)-1})")

        # print(out_tracks)
        t = out_tracks[idx]
        title = t.get("title", "")
        artist_name = t.get("artist", "")
        video_id = t.get("videoId", "")
        music_url = f"https://music.youtube.com/watch?v={video_id}" if video_id else ""

        selected = {
            "index": idx,
            "title": title,
            "artist": artist_name,
            "videoId": video_id,
            "music_url": music_url
        }

    except requests.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Upstream HTTP error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Step 2: call lyrics endpoint (if RAPIDAPI_KEY present)
    if not RAPIDAPI_KEY:
        return {"selected_track": selected, "lyrics_response": {"status": 500, "error": "Missing RAPIDAPI_KEY environment variable"}}

    lyrics_response = fetch_lyrics(title, artist_name)
    verses = []
    if lyrics_response.get("data"):
        verses = detect_verses(lyrics_response.get("data"), gap_threshold=8.0)
        for v in verses:
            print(f"Verse {v['index']+1}: starts at {v['start_time']}s → '{v['first_line']}'")
    next_song_dt["title"] = title
    next_song_dt["videoId"] = video_id

    if verses:
        next_song_dt["timestamp"] = int(verses[0]['start_time'])
    return {"selected_track": selected, "verse": verses}