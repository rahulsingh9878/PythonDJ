# app.py
import os
import json
import time
import requests
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import FastAPI, Query, Form, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from ytmusicapi import YTMusic
from utils import (
    generate_qr_base64
)
from fastapi.templating import Jinja2Templates
import copy
import random
import asyncio
from recommender_system import AsyncIndianMusicRecommender



app = FastAPI(title="YTMusic -> Lyrics FastAPI (no forward refs)", version="1.0")

# Initialize Global Recommender
recommender = AsyncIndianMusicRecommender()

@app.on_event("startup")
async def startup_event():
    """Start building the music database in the background on app startup."""
    asyncio.create_task(recommender.build_all_collections())

origins = [
    "https://rahulsingh9878.github.io",
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
default_context = {"recLimit": 30, "maxVol": 100}
next_song_dt = {"title": None, "videoId": None, "timestamp": 20}
templates = Jinja2Templates(directory="templates")
RESULT_CACHE = {}  # Simple cache for search results


class DJConnectionManager:
    def __init__(self):
        # All connected clients
        self.all_connections: List[WebSocket] = []
        # Clients identified as "player" (the main DJ screen)
        self.player_connections: List[WebSocket] = []
        # Clients identified as "controller" (phone remotes)
        self.controller_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket, role: str = "controller"):
        await websocket.accept()
        self.all_connections.append(websocket)
        if role == "player":
            self.player_connections.append(websocket)
        else:
            self.controller_connections.append(websocket)
        print(f"New {role} connected. Total: {len(self.all_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.all_connections:
            self.all_connections.remove(websocket)
        if websocket in self.player_connections:
            self.player_connections.remove(websocket)
        if websocket in self.controller_connections:
            self.controller_connections.remove(websocket)

    async def broadcast(self, message: dict, sender: WebSocket = None, target_role: str = None):
        """
        Broadcasts a message.
        target_role: "player", "controller", or None (all)
        """
        targets = self.all_connections
        if target_role == "player":
            targets = self.player_connections
        elif target_role == "controller":
            targets = self.controller_connections

        for connection in list(targets):
            if connection == sender:
                continue
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

manager = DJConnectionManager()

@app.websocket("/ws/sync")
async def websocket_sync_hub(websocket: WebSocket, role: str = Query("controller")):
    """
    Unified WebSocket Hub for all DJ operations.
    Expected message format: {"type": "play|vol|control|qr|ping", "data": {...}}
    """
    await manager.connect(websocket, role)
    # Send initial state (e.g. current volume)
    global default_context
    await websocket.send_json({"type": "vol", "data": {"volume": default_context.get("maxVol", 100)}})
    
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            msg_data = data.get("data")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "ts": time.time()})
            
            elif msg_type == "play":
                # Broadcast video update to everyone (especially players)
                await manager.broadcast({"type": "play", "data": msg_data}, sender=websocket)
            
            elif msg_type == "vol":
                default_context["maxVol"] = msg_data.get("volume")
                # Sync volume to all other controllers and players
                await manager.broadcast({"type": "vol", "data": msg_data}, sender=websocket)
            
            elif msg_type == "control":
                # Sync playback control to everyone
                await manager.broadcast({"type": "control", "data": msg_data}, sender=websocket)
            
            elif msg_type == "qr":
                url = msg_data.get("url")
                if url:
                    img_base64 = generate_qr_base64(url)
                    await websocket.send_json({"type": "qr", "data": {"img": img_base64, "url": url}})

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket Error: {e}")
        manager.disconnect(websocket)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass

# Legacy endpoints kept for backward compatibility during transition if needed, 
# but we should move everything to /ws/sync
@app.websocket("/ws/")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.receive_text()
    except: pass

@app.websocket("/ws/vol/")
async def websocket_vol_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            vol = await websocket.receive_text()
            await manager.broadcast({"type": "vol", "data": {"volume": vol}})
    except: pass

@app.websocket("/ws/qr/")
async def websocket_qr_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            url = await websocket.receive_text()
            if url:
                img_base64 = generate_qr_base64(url)
                await websocket.send_text(img_base64)
    except: pass

@app.websocket("/ws/player/")
async def websocket_player_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast({"type": "control", "data": json.loads(data)})
    except: pass



@app.get("/", response_class=HTMLResponse)
async def index_webview(request: Request):
    # global default_context
    # print(default_context)
    default_context["request"] = request
    if "music_type" not in default_context:
        default_context["music_type"] = "songs"
    return templates.TemplateResponse("recommendations.html", default_context)
    

@app.post("/recommendations/")
async def get_recommendations_as_webview(request: Request,
                        query: str = Form(..., example="MASAKALI"), 
                        limit: int = Form(20, ge=1, le=50),
                        nextPlay: bool = Form(False),
                        maxVol: int = Form(100, ge=1, le=100),
                        music_type: str = Form("songs"),
                        videoId: Optional[str] = Form(None),
                        refresh: bool = Form(False)):
    """
    Search a song on YouTube Music (by query) and return top recommendations (default limit 10).
    Returns a plain JSON dict to avoid Pydantic forward-ref issues.
    """
    print(f"Searching for: {query} (type: {music_type}, videoId: {videoId}, refresh: {refresh})")
    global out_tracks
    global default_context
    try:
        target_id = None
        exclude_title = None

        if refresh and out_tracks:
            # Anchor recommendations to the first track but don't play it
            first = out_tracks[0]
            target_id = first.get("videoId")
            query = first.get("title")
            exclude_title = query.lower()
        elif nextPlay:
            # If videoId is provided from frontend, use it; otherwise look it up in out_tracks
            target_id = videoId if videoId else (find_video_id(out_tracks, query) if out_tracks else None)
            exclude_title = query.lower()
            
            if target_id:
                play_data = {
                    "videoId": target_id,
                    "title": query,
                    "timestamp": 20
                }
                await manager.broadcast({"type": "play", "data": play_data})

        # Check cache first to avoid redundant API calls
        cache_key = f"{query}_{limit}"
        if videoId:
            cache_key += f"_{videoId}"
            
        if cache_key in RESULT_CACHE and not refresh:
            cached_context = RESULT_CACHE[cache_key]
            if request.headers.get("Accept") == "application/json":
                return JSONResponse(content=cached_context)
            return templates.TemplateResponse("recommendations.html", {**cached_context, "request": request})

        def process_results(results, result_type, filter_title=None):
            """Optimized result processing with label detection and high-res thumbnails"""
            if not results:
                return []
            
            processed = []
            for t in results:
                title = t.get("title", "")
                if not title:
                    continue
                
                # Filter out same titles if requested
                if filter_title and title.lower() == filter_title:
                    continue
                    
                artists = t.get("artists", [])
                artist_name = artists[0]["name"] if artists else ""
                video_id = t.get("videoId", "")
                if not video_id:
                    continue

                # --- NEW: Label Detection ---
                title_lower = title.lower()
                labels = []
                
                # Check for labels
                if any(x in title_lower for x in ["official video", "official music video", "(official video)", "official audio"]):
                    labels.append("Official")
                if any(x in title_lower for x in ["remix", "re-mix", "rmx"]):
                    labels.append("Remix")
                if any(x in title_lower for x in ["slowed", "slowed + reverb", "slowed and reverb"]):
                    labels.append("Slowed")
                if "live" in title_lower and "deliver" not in title_lower:
                    labels.append("Live")
                if any(x in title_lower for x in ["lyrical", "lyrics"]):
                    labels.append("Lyrics")
                if "cover" in title_lower:
                    labels.append("Cover")
                if "mashup" in title_lower:
                    labels.append("Mashup")
                
                # --- NEW: Sorting Weight ---
                # Give higher weight to official content
                weight = 0
                if "Official" in labels: weight += 10
                if result_type == "song" and t.get("type") == "MUSIC_VIDEO_TYPE_OFFICIAL_RELEASE": weight += 5

                # ytmusicapi search results use 'thumbnails', watch playlist uses 'thumbnail'
                thumbnails = t.get("thumbnails", t.get("thumbnail", []))
                thumbnail_url = ""
                
                if thumbnails:
                    if isinstance(thumbnails, list) and len(thumbnails) > 0 and isinstance(thumbnails[0], list):
                        thumbnails = thumbnails[0]
                    
                    if isinstance(thumbnails, list) and len(thumbnails) > 0:
                        try:
                            best_thumb = max(thumbnails, key=lambda x: int(x.get('width', 0)) * int(x.get('height', 0)))
                            thumbnail_url = best_thumb.get("url", "")
                        except:
                            thumbnail_url = thumbnails[0].get("url", "")
                    elif isinstance(thumbnails, dict):
                        thumbnail_url = thumbnails.get("url", "")

                if thumbnail_url and "googleusercontent.com" in thumbnail_url:
                    if "=" in thumbnail_url:
                        base_url = thumbnail_url.split("=")[0]
                        thumbnail_url = f"{base_url}=w512-h512-l90-rj"
                    elif "-s" in thumbnail_url:
                        base_name = thumbnail_url.split("-s")[0]
                        thumbnail_url = f"{base_name}-s512-c"
                
                if not thumbnail_url and video_id:
                    thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                
                url = f"https://music.youtube.com/watch?v={video_id}"
                
                processed.append({
                    "title": title,
                    "artist": artist_name,
                    "videoId": video_id,
                    "music_url": url, 
                    "thumbnail": thumbnail_url,
                    "type": result_type,
                    "labels": labels,
                    "weight": weight
                })
            
            # Sort by weight descending (Official first)
            processed.sort(key=lambda x: x['weight'], reverse=True)
            return processed

        def fetch_song_search():
            """Fetch initial song search results"""
            try:
                return yt.search(query, filter="songs", limit=3)
            except Exception as e:
                print(f"Error in song search: {e}")
                return []

        def fetch_video_search():
            """Fetch initial video search results"""
            try:
                return yt.search(query, filter="videos", limit=3)
            except Exception as e:
                print(f"Error in video search: {e}")
                return []

        def fetch_song_recommendations(video_id):
            """Fetch song recommendations based on video ID"""
            try:
                return yt.get_watch_playlist(videoId=video_id)
            except Exception as e:
                print(f"Error fetching song recommendations: {e}")
                return {"tracks": []}

        def fetch_video_recommendations(video_id):
            """Fetch video recommendations based on video ID"""
            try:
                return yt.get_watch_playlist(videoId=video_id)
            except Exception as e:
                print(f"Error fetching video recommendations: {e}")
                return {"tracks": []}

        # Phase 1: Parallel search for both songs and videos
        with ThreadPoolExecutor(max_workers=2) as executor:
            song_search_future = executor.submit(fetch_song_search)
            video_search_future = executor.submit(fetch_video_search)
            
            song_search_results = song_search_future.result()
            video_search_results = video_search_future.result()

        # Process initial search results
        song_tracks = process_results(song_search_results, "song", filter_title=exclude_title)
        video_tracks = process_results(video_search_results, "video", filter_title=exclude_title)

        # Phase 2: Parallel fetch recommendations (only if we have initial results or a target_id)
        song_recs_future = None
        video_recs_future = None
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            if target_id or song_tracks:
                anchor_id = target_id if target_id else song_tracks[0]["videoId"]
                song_recs_future = executor.submit(fetch_song_recommendations, anchor_id)
            if target_id or video_tracks:
                anchor_id = target_id if target_id else video_tracks[0]["videoId"]
                video_recs_future = executor.submit(fetch_video_recommendations, anchor_id)
            
            # Get recommendations results
            if song_recs_future:
                song_recs_data = song_recs_future.result()
                song_recs = process_results(song_recs_data.get("tracks", []), "song", filter_title=exclude_title)
                # Filter out duplicates and add to song_tracks
                existing_ids = {t["videoId"] for t in song_tracks}
                if target_id: existing_ids.add(target_id) # Ensure playing song isn't added back
                
                for r in song_recs:
                    if r["videoId"] not in existing_ids:
                        song_tracks.append(r)
                        existing_ids.add(r["videoId"])
                        if len(song_tracks) >= limit:
                            break
            
            if video_recs_future:
                video_recs_data = video_recs_future.result()
                video_recs = process_results(video_recs_data.get("tracks", []), "video", filter_title=exclude_title)
                # Filter out duplicates and add to video_tracks
                existing_ids = {t["videoId"] for t in video_tracks}
                if target_id: existing_ids.add(target_id)
                
                for r in video_recs:
                    if r["videoId"] not in existing_ids:
                        video_tracks.append(r)
                        existing_ids.add(r["videoId"])
                        if len(video_tracks) >= limit:
                            break

        # --- Custom Reordering for Selection (nextPlay) or Refresh ---
        if nextPlay or refresh:
            # Fallback if target_id is still missing
            if not target_id:
                if song_tracks: target_id = song_tracks[0]["videoId"]
                elif video_tracks: target_id = video_tracks[0]["videoId"]

            def reorder_for_selection(tracks, tid, q, is_refresh):
                if not tracks: return []
                
                playing = None
                others = []
                q_lower = q.lower()
                
                # 1. Extract playing song by ID (only if not refreshing, or keep it for filtering)
                if tid:
                    for t in tracks:
                        if t.get('videoId') == tid:
                            playing = t
                        else:
                            others.append(t)
                else:
                    others = tracks

                # 2. Fallback: Extract playing song by Title match if ID failed
                if not playing and others:
                    for i, t in enumerate(others):
                        t_title = t.get('title', '').lower()
                        if q_lower == t_title or q_lower in t_title:
                            playing = others.pop(i)
                            break
                
                # 3. Final Fallback: If still nothing and nextPlay, just take the first one
                if not playing and others and not is_refresh:
                    playing = others.pop(0)
                
                # 4. Partition others into matches and non-matches
                matches = []
                non_matches = []
                for t in others:
                    t_title = t.get('title', '').lower()
                    if q_lower in t_title:
                        matches.append(t)
                    else:
                        non_matches.append(t)
                
                # 5. Randomize both categories (keeping it fresh)
                random.shuffle(matches)
                random.shuffle(non_matches)
                
                # 6. Construct Final Order
                final = []
                # If nextPlay (manually selected a song), put it at top
                if playing and not is_refresh:
                    final.append(playing)
                
                final.extend(non_matches)
                final.extend(matches)
                
                # If refresh, the 'playing' song is completely excluded (not added back)
                return final

            song_tracks = reorder_for_selection(song_tracks, target_id, query, refresh)
            video_tracks = reorder_for_selection(video_tracks, target_id, query, refresh)

        # Combine them for the global out_tracks
        out_tracks = song_tracks + video_tracks
        
        # Add index to each for the template
        for idx, t in enumerate(out_tracks):
            t["index"] = idx

        context = {
            "query": query,
            "tracks": out_tracks,
            "song_tracks": song_tracks,
            "video_tracks": video_tracks,
            "recLimit": limit,
            "maxVol": maxVol,
            "music_type": music_type,
        }

        default_context = copy.deepcopy(context)
        
        # Store in cache for future requests
        RESULT_CACHE[cache_key] = context

        # Check for AJAX/API request - return JSON if requested
        if request.headers.get("Accept") == "application/json":
            return JSONResponse(content=context)

        context["request"] = request
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


def fetch_lyrics(title: str, artist: str = None, browseId: str = None, delay: float = 0.5) -> dict:
    """
    Fetch lyrics, trying YouTube Music first (free/official), then falling back to RapidAPI.

    Args:
        title (str): Song title
        artist (str, optional): Artist name
        browseId (str, optional): The detailed song ID (not videoId) needed for YT lyrics.
        delay (float, optional): Sleep time for RapidAPI fallback

    Returns:
        dict: Standardized structure: { "status": 200, "data": { "lyrics": "...", "source": "YT"|"RapidAPI" } }
    """

    # 1. Try YouTube Music Lyrics (Official & Free)
    if browseId:
        try:
            print(f"Fetching YT lyrics for browseId: {browseId}")
            lyrics_data = yt.get_lyrics(browseId)
            if lyrics_data and "lyrics" in lyrics_data:
                return {
                    "status": 200, 
                    "data": {
                        "lyrics": lyrics_data["lyrics"], 
                        "source": "YT",
                        "provider": lyrics_data.get("source", "YouTube Music")
                    }
                }
        except Exception as e:
            print(f"YT lyrics fetch failed: {e}")

    # 2. Fallback to RapidAPI (Musixmatch)
    if not RAPIDAPI_KEY:
        # If no key and YT failed, we have nothing
        return {"status": 404, "error": "No lyrics found (YT failed, no RapidAPI key)"}

    # ... existing RapidAPI logic ...
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
        print(f"Falling back to RapidAPI for: {title}")
        resp = requests.get(RAPIDAPI_URL, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        # Wrap it to preserve existing structure while noting source
        return {
            "status": data.get("status", resp.status_code), 
            "data": data.get("data", data),
            "source": "RapidAPI"
        }
    except requests.HTTPError as e:
        print(f"RapidAPI failed: {e}") 
        return {"status": 502, "error": str(e)}
    except Exception as e:
        return {"status": 500, "error": str(e)}

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

    # Step 2: call lyrics endpoint
    # Extract browseId if available (often in 'browseId' or 'album' -> 'id' depending on object)
    # in search results, top-level 'browseId' is for the song.
    browse_id = t.get("browseId")
    
    lyrics_response = fetch_lyrics(title, artist_name, browseId=browse_id)
    
    verses = []
    lyrics_data = lyrics_response.get("data")
    
    if lyrics_data:
        if lyrics_response.get("source") == "YT":
             # Process plain text lyrics from YT
             raw_text = lyrics_data.get("lyrics", "")
             # Simple split by paragraphs for now to simulate verses
             blocks = raw_text.split("\n\n")
             for i, block in enumerate(blocks):
                 if block.strip():
                     verses.append({
                         "index": i,
                         "start_time": 0 if i == 0 else -1, # No timestamps in scraping usually
                         "end_time": -1,
                         "first_line": block.strip().split("\n")[0] if block else "",
                         "text": block.strip()
                     })
        else:
            # Existing RapidAPI logic
            verses = detect_verses(lyrics_data, gap_threshold=8.0)
            for v in verses:
                print(f"Verse {v['index']+1}: starts at {v['start_time']}s → '{v['first_line']}'")
            
    next_song_dt["title"] = title
    next_song_dt["videoId"] = video_id
    
    # Use first verse time if available
    if verses and verses[0]['start_time'] >= 0:
        next_song_dt["timestamp"] = int(verses[0]['start_time'])
    else:
        # Default start time if no time-synced lyrics
        next_song_dt["timestamp"] = 20

    return {"selected_track": selected, "verse": verses, "source": lyrics_response.get("source", "Unknown")}

@app.post("/radio/")
async def start_radio_mode(
    videoId: str = Form(...),
    limit: int = Form(50)
):
    """
    Start 'Smart Radio' mode using multithreading for maximum performance.
    - Fetches Audio Playlist immediately (Thread 1)
    - Resolves Video ID in background (Thread 2) -> Then Fetches Video Playlist (Thread 2)
    """
    print(f"Starting Radio Mode for videoId: {videoId} (Async/Threaded)")
    global out_tracks
    
    loop = asyncio.get_running_loop()

    # --- BLOCKING HELPERS (Run in Threads) ---
    def resolve_video_id(original_id):
        """Checks if ID is Audio-only and searches for video version."""
        try:
            # Check metadata
            metadata = yt.get_song(original_id)
            video_details = metadata.get("videoDetails", {})
            music_type = video_details.get("musicVideoType", "")
            title = video_details.get("title", "")

            if music_type == "MUSIC_VIDEO_TYPE_ATV":
                print(f"Detected Audio-only Track ({original_id}). Searching for video version...")
                search_query = f"{title} video song"
                video_results = yt.search(search_query, filter="videos", limit=1)
                if video_results:
                    new_id = video_results[0].get("videoId")
                    if new_id:
                        print(f"Resolved Video Version: {new_id}")
                        return new_id
        except Exception as e:
            print(f"Video Resolution failed: {e}")
        return original_id # Fallback to original

    def fetch_playlist_blocking(vid, lim):
        return yt.get_watch_playlist(videoId=vid, limit=lim, radio=True)

    def process_radio_tracks(raw_list, label_type="Radio"):
        processed = []
        for t in raw_list:
            title = t.get("title", "")
            artists = t.get("artists", [])
            artist_name = artists[0]["name"] if artists else ""
            vid = t.get("videoId", "")
            thumbnails = t.get("thumbnail", [])
            thumbnail_url = thumbnails[-1]["url"] if isinstance(thumbnails, list) and thumbnails else ""

            if not vid: continue

            processed.append({
                "title": title,
                "artist": artist_name,
                "videoId": vid,
                "music_url": f"https://music.youtube.com/watch?v={vid}",
                "thumbnail": thumbnail_url,
                "type": "radio",
                "labels": [label_type],
                "weight": 5
            })
        return processed
    # -----------------------------------------

    try:
        # STEP 1: Start Audio Playlist Fetch (Immediate)
        audio_task = loop.run_in_executor(None, fetch_playlist_blocking, videoId, limit)

        # STEP 2: Start Video ID Resolution (Parallel)
        resolution_task = loop.run_in_executor(None, resolve_video_id, videoId)

        # Wait for Resolution
        video_seed_id = await resolution_task
        
        # STEP 3: Start Video Playlist Fetch (After Resolution)
        # Note: Audio fetch is still running in parallel!
        video_task = loop.run_in_executor(None, fetch_playlist_blocking, video_seed_id, limit)

        # STEP 4: Gather Results
        # audio_task might be done or still running. video_task just started.
        raw_audio, raw_video = await asyncio.gather(audio_task, video_task)
        
        # Process Results
        audio_tracks = process_radio_tracks(raw_audio.get("tracks", []), "Radio Mix")
        video_tracks = process_radio_tracks(raw_video.get("tracks", []), "Video Mix")

        # Update Global
        out_tracks = audio_tracks + video_tracks
        for idx, t in enumerate(out_tracks):
            t["index"] = idx

        return {
            "status": "success", 
            "message": "Dual Radio Started", 
            "tracks": audio_tracks, 
            "videos": video_tracks
        }

    except Exception as e:
        print(f"Error starting radio: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/charts/")
def get_charts(country: str = Query("IN", min_length=2, max_length=2)):
    """
    Get top charts for a specific country (default: IN).
    Returns 'top_songs', 'top_videos', 'trending' lists.
    """
    global out_tracks
    try:
        # charts = yt.get_charts(country=country) # DISABLED: Crashes often. using Recommender exclusively.
        
        # Use Async Recommender System exclusively
        print(f"Fetching charts for {country} using AsyncIndianMusicRecommender...")
        
        top_songs = []
        trending = []
        top_videos = []

        try:
            # Generate Playlist from Recommender
            dynamic_playlist = recommender.generate_dynamic_playlist(50)
            
            if dynamic_playlist:
                formatted_items = []
                for s in dynamic_playlist:
                    # Map to frontend structure
                    formatted_items.append({
                        "title": s["title"],
                        "artist": s["artist"],
                        "videoId": s["videoId"],
                        "browseId": "",
                        "music_url": s["music_url"],
                        "thumbnail": s["thumbnail"],
                        "type": "chart",
                        "labels": ["Trending", s.get("category", "")[:1].upper() + s.get("category", "")[1:]],
                        "weight": 10
                    })
                
                # Split for UI variety (Top Songs vs Trending)
                top_songs = formatted_items[:25]
                trending = formatted_items[25:]
                
                print(f"Recommender succeeded. {len(top_songs)} songs, {len(trending)} trending.")

            else:
                 raise Exception("Recommender database empty/building")

        except Exception as e:
            print(f"Recommender failed/not ready ({e}). Using Hardcoded Failsafe.")
            
            # Failsafe Hits
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

    except Exception as e:
        print(f"Error fetching charts: {e}")
        # Return empty structure instead of crashing
        return {
            "country": country,
            "top_songs": [],
            "top_videos": [],
            "trending": []
        }