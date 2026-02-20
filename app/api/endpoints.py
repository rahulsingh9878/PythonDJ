from fastapi import APIRouter, Request, Form, Query, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import Optional, List
import copy
import random
import time
import requests
import asyncio
from concurrent.futures import ThreadPoolExecutor

from ..services.music_service import music_service
from ..services.connection_manager import manager
from ..core.state import out_tracks, default_context, next_song_dt, RESULT_CACHE
from ..utils.helpers import find_video_id, detect_verses
from ..core.config import RAPIDAPI_KEY, RAPIDAPI_HOST, RAPIDAPI_URL

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.on_event("startup")
async def startup_event():
    """Start building the music database in the background on app startup."""
    await music_service.initialize()

@router.get("/", response_class=HTMLResponse)
async def index_webview(request: Request):
    default_context["request"] = request
    if "music_type" not in default_context:
        default_context["music_type"] = "songs"
    return templates.TemplateResponse("recommendations.html", default_context)

@router.post("/search/")
async def search_endpoint(
    request: Request,
    query: str = Form(..., example="MASAKALI"), 
    limit: int = Form(30, ge=1, le=50),
    nextPlay: bool = Form(False),
    maxVol: int = Form(100, ge=1, le=100),
    music_type: str = Form("songs"),
    videoId: Optional[str] = Form(None),
    refresh: bool = Form(False)
):
    """
    Search a song on YouTube Music (by query) and return top recommendations (default limit 10).
    """
    print(f"Searching for: {query} (type: {music_type}, videoId: {videoId}, refresh: {refresh})")
    
    try:
        if nextPlay and videoId:
            # Use new Play & Radio flow
            context = await music_service.play_and_populate(
                video_id=videoId,
                title=query,
                limit=limit,
                maxVol=maxVol,
                music_type=music_type
            )
        else:
            # Traditional Search flow
            context = await music_service.perform_search(
                query=query, 
                limit=limit, 
                nextPlay=nextPlay, 
                maxVol=maxVol, 
                music_type=music_type, 
                videoId=videoId, 
                refresh=refresh
            )

        if request.headers.get("Accept") == "application/json":
            return JSONResponse(content=context)


        context["request"] = request
        return templates.TemplateResponse("recommendations.html", context)

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/suggestions/")
def get_search_suggestions(query: str = Query(..., min_length=1)):
    """
    Get search suggestions for a given query.
    """
    try:
        suggestions = music_service.get_suggestions(query)
        # Standardize response
        # ytmusicapi usually returns a list of dicts with 'title' runs, or sometimes simple things.
        # But commonly it attempts to look like the web suggestion.
        # Let's inspect structure if we could, but here we just pass it or extract strings.
        
        # If it returns list of dicts with 'title', extract it.
        # If list of strings, just return.
        
        final_list = []
        for s in suggestions:
            if isinstance(s, dict):
                 # Try to find text
                 if 'title' in s: final_list.append(s['title'])
                 elif 'query' in s: final_list.append(s['query'])
                 else: final_list.append(str(s))
            elif isinstance(s, str):
                final_list.append(s)
        
        # Deduplicate
        final_list = list(dict.fromkeys(final_list))
        
        return {"suggestions": final_list}
    except Exception as e:
        print(f"Suggestion error: {e}")
        return {"suggestions": []}


@router.get("/lyrics/")
def get_lyrics_endpoint(title: str = Query(..., example="MASAKALI"), artist: Optional[str] = Query(None)):
    """
    Directly calls RapidAPI (legacy endpoint)
    """
    # For now, replicate logic or call service.
    # The original endpoint returned wrapper around RapidAPI response.
    # We can use music_service.fetch_lyrics but it attempts YT first if browseId provided.
    # Here we don't have browseId.
    
    if not RAPIDAPI_KEY:
         raise HTTPException(status_code=500, detail="Missing RAPIDAPI_KEY")
    
    # We can adapt music_service.fetch_lyrics to force RapidAPI if we want, or rely on its fallback.
    # But `fetch_lyrics` does a YT check only if browseId is present.
    # So calling it without browseId should fall back to RapidAPI instantly.
    
    result = music_service.fetch_lyrics(title, artist, browseId=None, delay=0.5)
    if "error" in result:
         # Need to map internal errors to HTTP exceptions to match old behavior
         # Original code raised HTTPException on some errors.
         if result["status"] == 500: raise HTTPException(status_code=500, detail=result["error"])
         if result["status"] == 502: raise HTTPException(status_code=502, detail=result["error"])
         if result["status"] == 404: raise HTTPException(status_code=404, detail=result["error"])
    
    return result


@router.get("/track/{idx}/")
def get_track_lyrics_by_index(idx: int):
    from ..core import state
    if idx < 0:
        raise HTTPException(status_code=400, detail="idx must be >= 0")

    try:
        if idx >= len(state.out_tracks):
            raise HTTPException(status_code=400, detail=f"idx {idx} out of range (0..{len(state.out_tracks)-1})")

        t = state.out_tracks[idx]
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

    # Fetch lyrics
    browse_id = t.get("browseId") # Might be None
    lyrics_response = music_service.fetch_lyrics(title, artist_name, browseId=browse_id)
    
    verses = []
    lyrics_data = lyrics_response.get("data")
    
    if lyrics_data:
        if lyrics_response.get("source") == "YT":
             raw_text = lyrics_data.get("lyrics", "")
             blocks = raw_text.split("\n\n")
             for i, block in enumerate(blocks):
                 if block.strip():
                     verses.append({
                         "index": i,
                         "start_time": 0 if i == 0 else -1,
                         "end_time": -1,
                         "first_line": block.strip().split("\n")[0] if block else "",
                         "text": block.strip()
                     })
        else:
            verses = detect_verses(lyrics_data, gap_threshold=8.0)
            
    state.next_song_dt["title"] = title
    state.next_song_dt["videoId"] = video_id
    
    if verses and verses[0].get('start_time', -1) >= 0:
        state.next_song_dt["timestamp"] = int(verses[0]['start_time'])
    else:
        state.next_song_dt["timestamp"] = 20

    return {"selected_track": selected, "verse": verses, "source": lyrics_response.get("source", "Unknown")}

@router.post("/radio/")
async def start_radio_mode(
    videoId: str = Form(...),
    limit: int = Form(50)
):
    print(f"Starting Radio Mode for videoId: {videoId}")
    try:
        result = await music_service.start_radio(video_id=videoId, limit=limit)
        return result
    except Exception as e:
        print(f"Error starting radio: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/charts/")
def get_charts(country: str = Query("IN", min_length=2, max_length=2)):
    print(f"Fetching charts for {country} using AsyncIndianMusicRecommender...")
    
    top_songs = []
    trending = []
    top_videos = [] # Not used in output but var existed in original

    try:
        # Use Recommender via music_service
        dynamic_playlist = music_service.recommender.generate_dynamic_playlist(50)
        
        if dynamic_playlist:
            formatted_items = []
            for s in dynamic_playlist:
                formatted_items.append({
                    "title": s["title"],
                    "artist": s["artist"],
                    "videoId": s["videoId"],
                    "browseId": "",
                    "music_url": s.get("music_url", s.get("url", "")), # Safety check
                    "thumbnail": s["thumbnail"],
                    "type": "chart",
                    "labels": ["Trending", s.get("category", "")[:1].upper() + s.get("category", "")[1:]],
                    "weight": 10
                })
            
            top_songs = formatted_items[:25]
            trending = formatted_items[25:]
        else:
             raise Exception("Recommender returned empty")

    except Exception as e:
        print(f"Recommender failed/not ready ({e}). Using Hardcoded Failsafe.")
        failsafe_tracks = [
            {"videoId": "k4yXQkGDbLY", "title": "Shape of You", "artist": "Ed Sheeran", "thumbnail": "https://i.ytimg.com/vi/k4yXQkGDbLY/hqdefault.jpg"},
            {"videoId": "JGwWNGJdvx8", "title": "Despacito", "artist": "Luis Fonsi", "thumbnail": "https://i.ytimg.com/vi/JGwWNGJdvx8/hqdefault.jpg"},
            {"videoId": "OPf0YbXqDm0", "title": "Uptown Funk", "artist": "Mark Ronson", "thumbnail": "https://i.ytimg.com/vi/OPf0YbXqDm0/hqdefault.jpg"},
            {"videoId": "09R8_2nJtjg", "title": "Sugar", "artist": "Maroon 5", "thumbnail": "https://i.ytimg.com/vi/09R8_2nJtjg/hqdefault.jpg"}
        ]
        
        failsafe_processed = []
        for t in failsafe_tracks:
             failsafe_processed.append({
                "title": t["title"], "artist": t["artist"], "videoId": t["videoId"],
                "browseId": "", "music_url": f"https://music.youtube.com/watch?v={t['videoId']}",
                "thumbnail": t["thumbnail"], "type": "chart", "labels": ["Hit"], "weight": 10
             })
        top_songs = failsafe_processed
        trending = failsafe_processed
    
    return {
        "country": country,
        "top_songs": top_songs,
        "top_videos": top_videos,
        "trending": trending
    }
