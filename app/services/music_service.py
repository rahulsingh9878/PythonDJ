import time
import requests
import asyncio
import random
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

from ytmusicapi import YTMusic
from ..core.config import RAPIDAPI_KEY, RAPIDAPI_HOST, RAPIDAPI_URL
from ..utils.helpers import detect_verses
from .recommender_system import AsyncIndianMusicRecommender

class MusicService:
    def __init__(self):
        # Initialize YTMusic (anonymous). Keep a single instance.
        self.yt = YTMusic()
        self.recommender = AsyncIndianMusicRecommender()
        self.out_tracks = [] # Could be stateful per session if multiple users, but app.py implies single instance global state for now

    async def initialize(self):
        """Start building the music database in the background on app startup."""
        asyncio.create_task(self.recommender.build_all_collections())

    def get_watch_playlist(self, videoId, limit=20, radio=False):
        return self.yt.get_watch_playlist(videoId=videoId, limit=limit, radio=radio)
        
    def get_song(self, videoId):
        return self.yt.get_song(videoId)

    def search(self, query, filter_type="songs", limit=3):
        return self.yt.search(query, filter=filter_type, limit=limit)

    def get_suggestions(self, query: str):
        """Fetch search suggestions from YouTube Music"""
        try:
             return self.yt.get_search_suggestions(query)
        except Exception as e:
            print(f"Error fetching suggestions: {e}")
            return []

    def process_results(self, results, result_type, filter_title=None):
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

            # --- Label Detection ---
            title_lower = title.lower()
            labels = []
            
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
            
            # --- Sorting Weight ---
            weight = 0
            if "Official" in labels: weight += 10
            if result_type == "song" and t.get("type") == "MUSIC_VIDEO_TYPE_OFFICIAL_RELEASE": weight += 5

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

    def fetch_lyrics(self, title: str, artist: str = None, browseId: str = None, delay: float = 0.5) -> dict:
        """
        Fetch lyrics, trying YouTube Music first (free/official), then falling back to RapidAPI.
        """

        # 1. Try YouTube Music Lyrics (Official & Free)
        if browseId:
            try:
                print(f"Fetching YT lyrics for browseId: {browseId}")
                lyrics_data = self.yt.get_lyrics(browseId)
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
            return {"status": 404, "error": "No lyrics found (YT failed, no RapidAPI key)"}

        params = {"terms": title}
        if artist:
            params["artist"] = artist

        headers = {
            "x-rapidapi-key": RAPIDAPI_KEY,
            "x-rapidapi-host": RAPIDAPI_HOST
        }

        time.sleep(delay)

        try:
            print(f"Falling back to RapidAPI for: {title}")
            resp = requests.get(RAPIDAPI_URL, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
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

    async def play_and_populate(self, video_id: str, title: str, limit: int = 30, maxVol: int = 100, music_type: str = "songs"):
        """
        New Play Flow:
        1. Instantly broadcast play command.
        2. Use radio logic (related tracks) to populate the background list.
        """
        from ..services.connection_manager import manager
        from ..core import state
        import copy

        # 1. Immediate Broadcast (Fast Lane)
        play_data = {
            "videoId": video_id,
            "title": title,
            "timestamp": 20
        }
        await manager.broadcast({"type": "play", "data": play_data})

        # 2. Use Radio Logic to fetch new list
        radio_result = await self.start_radio(video_id=video_id, limit=limit)
        
        # 3. Format context for UI (Merging radio results with current state like volume)
        context = {
            "query": title,
            "tracks": state.out_tracks,
            "video_tracks": radio_result.get("video_tracks", []),
            "song_tracks": radio_result.get("song_tracks", []),
            "recLimit": limit,
            "maxVol": maxVol,
            "music_type": music_type,
        }

        # Update global default_context
        state.default_context.clear()
        state.default_context.update(copy.deepcopy(context))
        
        return context

    async def perform_search(self, query: str, limit: int = 30, nextPlay: bool = False, maxVol: int = 100, music_type: str = "songs", videoId: Optional[str] = None, refresh: bool = False):
        from ..core import state
        from ..services.connection_manager import manager
        from ..utils.helpers import find_video_id
        
        target_id = None
        exclude_title = None

        if refresh and state.out_tracks:
            first = state.out_tracks[0]
            target_id = first.get("videoId")
            query = first.get("title")
            exclude_title = query.lower()
        elif nextPlay:
            target_id = videoId if videoId else (find_video_id(state.out_tracks, query) if state.out_tracks else None)
            exclude_title = query.lower()
            
            if target_id:
                play_data = {
                    "videoId": target_id,
                    "title": query,
                    "timestamp": 20
                }
                await manager.broadcast({"type": "play", "data": play_data})

        # --- Helper wrappers for ThreadPoolExecutor ---
        def fetch_song_search():
             try: return self.search(query, filter_type="songs", limit=limit)
             except Exception as e: print(f"Error in song search: {e}"); return []

        def fetch_video_search():
             try: return self.search(query, filter_type="videos", limit=limit)
             except Exception as e: print(f"Error in video search: {e}"); return []

        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=2) as executor:
            song_search_future = executor.submit(fetch_song_search)
            video_search_future = executor.submit(fetch_video_search)
            song_search_results = await loop.run_in_executor(None, song_search_future.result)
            video_search_results = await loop.run_in_executor(None, video_search_future.result)

        song_tracks = self.process_results(song_search_results, "song", filter_title=exclude_title)
        video_tracks = self.process_results(video_search_results, "video", filter_title=exclude_title)

        if nextPlay or refresh:
            if not target_id:
                if song_tracks: target_id = song_tracks[0]["videoId"]
                elif video_tracks: target_id = video_tracks[0]["videoId"]

            song_tracks = self.reorder_for_selection(song_tracks, target_id, query, refresh)
            video_tracks = self.reorder_for_selection(video_tracks, target_id, query, refresh)

        new_out_tracks = song_tracks + video_tracks
        for idx, t in enumerate(new_out_tracks):
            t["index"] = idx

        state.out_tracks.clear()
        state.out_tracks.extend(new_out_tracks)

        context = {
            "query": query,
            "tracks": state.out_tracks,
            "video_tracks": video_tracks,
            "song_tracks": song_tracks,
            "recLimit": limit,
            "maxVol": maxVol,
            "music_type": music_type,
        }

        state.default_context.clear()
        import copy
        state.default_context.update(copy.deepcopy(context))
        return context

    def reorder_for_selection(self, tracks, tid, q, is_refresh):
        if not tracks: return []
        playing = None
        others = []
        q_lower = q.lower()
        
        if tid:
            for t in tracks:
                if t.get('videoId') == tid: playing = t
                else: others.append(t)
        else: others = tracks

        if not playing and others:
            for i, t in enumerate(others):
                if q_lower in t.get('title', '').lower():
                    playing = others.pop(i)
                    break
        
        if not playing and others and not is_refresh:
            playing = others.pop(0)
        
        matches = []
        non_matches = []
        for t in others:
            if q_lower in t.get('title', '').lower(): matches.append(t)
            else: non_matches.append(t)
        
        random.shuffle(matches)
        random.shuffle(non_matches)
        
        final = []
        if playing and not is_refresh: final.append(playing)
        final.extend(non_matches)
        final.extend(matches)
        return final

    async def start_radio(self, video_id: str, limit: int = 50):
        """
        Refined Radio Logic: Ensures all results (both audio and video slots) are 
        Official Music Videos for a premium TV experience.
        """
        from ..core import state
        loop = asyncio.get_running_loop()

        def resolve_ids(original_id):
            """Resolves any ID to its Official Music Video counterpart. Returns {'audio': id, 'video': id}."""
            res = {"audio": original_id, "video": original_id}
            try:
                metadata = self.get_song(original_id)
                v_details = metadata.get("videoDetails", {})
                # Search for the video version
                title = v_details.get("title", "")
                artist = v_details.get("author", "")
                vq = f"{title} {artist} official music video"
                aq = f"{title} {artist} official audio song"
                video_results = self.search(vq, filter_type="videos", limit=1)
                audio_results = self.search(aq, filter_type="songs", limit=1)
                if video_results:
                    res["video"] = video_results[0].get("videoId") or original_id
                if audio_results:
                    res["audio"] = audio_results[0].get("videoId") or original_id
                print(res)
            except: pass
            return res

        def fetch_playlist_blocking(vid, lim):
            return self.get_watch_playlist(videoId=vid, limit=lim, radio=True)

        def process_results(raw_list, music_type="video", label_type="Video Mix"):
            processed = []
            for t in raw_list:
                vid = t.get("videoId")
                if not vid: continue
                title = t.get("title", "")
                artists = t.get("artists", [])
                artist_name = artists[0]["name"] if artists else ""
                
                thumbnails = t.get("thumbnail", t.get("thumbnails", []))
                thumb_url = ""
                if thumbnails:
                    if isinstance(thumbnails, list) and len(thumbnails) > 0:
                        thumb_url = thumbnails[-1].get("url", "")
                    elif isinstance(thumbnails, dict):
                        thumb_url = thumbnails.get("url", "")
                
                if thumb_url and "googleusercontent.com" in thumb_url:
                    base = thumb_url.split("=")[0] if "=" in thumb_url else thumb_url.split("-s")[0]
                    thumb_url = f"{base}=w512-h512-l90-rj"
                
                # Label Detection for videos
                labels = [label_type]
                title_l = title.lower()
                if any(x in title_l for x in ["official video", "music video"]): labels.append("Official")

                processed.append({
                    "title": title,
                    "artist": artist_name,
                    "videoId": vid,
                    "music_url": f"https://music.youtube.com/watch?v={vid}",
                    "thumbnail": thumb_url,
                    "type": music_type,
                    "labels": labels,
                    "weight": 10 if "Official" in labels else 5
                })
            return processed

        # 1. Resolve seed to video
        ids = await loop.run_in_executor(None, resolve_ids, video_id)
        video_seed = ids["video"]
        audio_seed = ids["audio"]

        # 2. Fetch Two Parallel Streams
        async def get_varied_mixes():
            raw_1 = await loop.run_in_executor(None, fetch_playlist_blocking, video_seed, limit)
            tracks_1 = raw_1.get("tracks", [])
            raw_2 = await loop.run_in_executor(None, fetch_playlist_blocking, audio_seed, limit)
            return tracks_1, raw_2.get("tracks", [])

        mix_1, mix_2 = await get_varied_mixes()
        
        # 3. Use separate processors for Songs and Videos
        video_tracks = process_results(mix_1, "video", "Video Mix")
        song_tracks = process_results(mix_2, "song", "Radio Mix")

        # Update global operational state
        final_list = song_tracks + video_tracks
        for i, t in enumerate(final_list): t["index"] = i
        
        state.out_tracks.clear()
        state.out_tracks.extend(final_list)

        # Build context to match Search Route structure
        current_max_vol = state.default_context.get("maxVol", 100)
        context = {
            "query": "Radio Mix", 
            "tracks": state.out_tracks,
            "song_tracks": song_tracks,
            "video_tracks": video_tracks,
            "recLimit": limit,
            "maxVol": current_max_vol,
            "status": "success"
        }

        print(final_list)
        # Sync Global Context (so all controllers see the new list)
        import copy
        state.default_context.clear()
        state.default_context.update(copy.deepcopy(context))

        return context

music_service = MusicService()
