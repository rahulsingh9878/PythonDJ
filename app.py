# app.py
import os
import time
import requests
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from ytmusicapi import YTMusic

# ---------- Configuration ----------
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")
RAPIDAPI_HOST = os.environ.get("RAPIDAPI_HOST", "spotify-web-api3.p.rapidapi.com")
RAPIDAPI_URL = f"https://{RAPIDAPI_HOST}/v1/social/spotify/musixmatchsearchlyrics"

# Initialize YTMusic (anonymous). Keep a single instance.
yt = YTMusic()

app = FastAPI(title="YTMusic -> Lyrics FastAPI (no forward refs)", version="1.0")


@app.get("/recommendations")
def get_recommendations(query: str = Query(..., example="MASAKALI"), limit: int = Query(10, ge=1, le=50)):
    """
    Search a song on YouTube Music (by query) and return top recommendations (default limit 10).
    Returns a plain JSON dict to avoid Pydantic forward-ref issues.
    """
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

        return {"query": query, "tracks": out_tracks}

    except requests.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Upstream HTTP error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/lyrics")
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
