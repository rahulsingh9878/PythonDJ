# app.py
import os
import time
import requests
from typing import Optional

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from ytmusicapi import YTMusic
from utils import detect_verses
from fastapi.templating import Jinja2Templates


app = FastAPI(title="YTMusic -> Lyrics FastAPI (no forward refs)", version="1.0")
origins = [
    "https://rahulsingh9878.github.io",
    "http://localhost", # (Optional) Also allow your local computer for testing
    "http://127.0.0.1", # (Optional)
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

@app.get("/recommendations/", response_class=HTMLResponse))
def get_recommendations(request: Request,
                        query: str = Query(..., example="MASAKALI"), 
                        limit: int = Query(10, ge=1, le=50)):
    """
    Search a song on YouTube Music (by query) and return top recommendations (default limit 10).
    Returns a plain JSON dict to avoid Pydantic forward-ref issues.
    """
    global out_tracks
    try:
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
            artist_name = artists[0]["name"] if artists else "Unknown Artist"
            video_id = t.get("videoId", "")
            url = f"https://music.youtube.com/watch?v={video_id}" if video_id else ""
            out_tracks.append({
                "index": idx,
                "title": title,
                "artist": artist_name,
                "videoId": video_id,
                "music_url": url
            })

        # return {"query": query, "tracks": out_tracks}
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

@app.get("/nextsong/")
def get_nextsong():
    global next_song_dt
    
    if next_song_dt["videoId"] is None:
        raise HTTPException(status_code=400, detail="No id found")
    
    return {"status": 200, "data": next_song_dt}
    
