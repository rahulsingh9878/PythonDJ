"""
Core music service.

MusicService is the single point of contact for all YouTube Music
operations: search, radio, lyrics, and track management.  It owns one
YTMusic instance and shares it with the recommender to avoid opening two
anonymous sessions.
"""

import asyncio
import copy
import hashlib
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import requests
import yt_dlp
from ytmusicapi import YTMusic

from ..core.cache import CacheBackend, NullCache, make_key
from ..core.config import settings
from ..core.state import app_state
from ..utils.helpers import find_video_id
from .recommender_system import AsyncIndianMusicRecommender

logger = logging.getLogger(__name__)


def _find_peaks(
    heatmap: List[Dict],
    min_value: float = 0.5,
    min_gap_seconds: float = 30.0,
    window: int = 3,
) -> List[Dict]:
    """
    Detect local maxima in a YouTube heatmap segment list.

    Each element in heatmap is expected to have:
        start_time (float), end_time (float), value (float 0–1)

    Returns peaks sorted by value descending, each dict including a
    'midpoint' key with the centre timestamp in seconds.
    """
    n = len(heatmap)
    peaks: List[Dict] = []

    for i in range(window, n - window):
        current = heatmap[i]["value"]
        if current < min_value:
            continue
        neighbors = [
            heatmap[i + offset]["value"]
            for offset in range(-window, window + 1)
            if offset != 0
        ]
        if current <= max(neighbors):
            continue

        midpoint = (heatmap[i]["start_time"] + heatmap[i]["end_time"]) / 2

        if peaks and (midpoint - peaks[-1]["midpoint"]) < min_gap_seconds:
            if current > peaks[-1]["value"]:
                peaks[-1] = {**heatmap[i], "midpoint": midpoint}
        else:
            peaks.append({**heatmap[i], "midpoint": midpoint})

    peaks.sort(key=lambda p: p["value"], reverse=True)
    return peaks


def _best_thumbnail(thumbnails) -> str:
    """
    Extract the highest-resolution thumbnail URL from the various shapes
    ytmusicapi can return (list of dicts, nested list, plain dict, …).
    Also upgrades Google-hosted thumbnails to 512 × 512.
    """
    if not thumbnails:
        return ""

    if (
        isinstance(thumbnails, list)
        and thumbnails
        and isinstance(thumbnails[0], list)
    ):
        thumbnails = thumbnails[0]

    url = ""
    if isinstance(thumbnails, list) and thumbnails:
        try:
            best = max(
                thumbnails,
                key=lambda x: int(x.get("width", 0)) * int(x.get("height", 0)),
            )
            url = best.get("url", "")
        except Exception:
            url = thumbnails[0].get("url", "")
    elif isinstance(thumbnails, dict):
        url = thumbnails.get("url", "")

    if url and "googleusercontent.com" in url:
        base = url.split("=")[0] if "=" in url else url.split("-s")[0]
        url = f"{base}=w512-h512-l90-rj"

    return url


def _clean_suggestions(raw: list) -> List[str]:
    """
    Normalise ytmusicapi suggestion objects into plain strings and
    deduplicate while preserving order.
    """
    seen: set = set()
    result: List[str] = []
    for item in raw:
        if isinstance(item, dict):
            text = item.get("title") or item.get("query") or str(item)
        else:
            text = str(item)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _query_hash(query: str) -> str:
    """Short stable hash of a search query for use in cache keys."""
    return hashlib.md5(query.lower().strip().encode()).hexdigest()[:12]


class MusicService:
    def __init__(self) -> None:
        self.yt = YTMusic()
        self.recommender = AsyncIndianMusicRecommender(yt=self.yt)
        self._cache: CacheBackend = NullCache()

    # ------------------------------------------------------------------
    # Cache injection (called once from main.py lifespan)
    # ------------------------------------------------------------------

    def set_cache(self, cache: CacheBackend) -> None:
        self._cache = cache

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Kick off the recommender warm-start as a background task."""
        asyncio.create_task(self._build_recommender())
        logger.info("MusicService initialised – recommender building in background")

    async def _build_recommender(self) -> None:
        """
        Redis-first recommender warm-start.

        1. Try to load the music_database from Redis (fast path — avoids 40+ API calls).
        2. On cache miss, run the full build then persist the result.
        """
        cache_key = make_key("recommender", "db")
        cached_db = await self._cache.get(cache_key)

        if cached_db is not None:
            self.recommender.music_database = cached_db
            total = sum(len(v) for v in cached_db.values())
            logger.info(
                "Recommender DB loaded from Redis – %d songs across %d categories",
                total,
                len(cached_db),
            )
            return

        # Cold start — fetch from YouTube Music
        await self.recommender.build_all_collections()

        # Persist so the next restart is instant
        await self._cache.set(
            cache_key,
            self.recommender.music_database,
            settings.redis_recommender_ttl,
        )
        total = sum(len(v) for v in self.recommender.music_database.values())
        logger.info(
            "Recommender DB persisted to Redis – %d songs, ttl=%ds",
            total,
            settings.redis_recommender_ttl,
        )

    # ------------------------------------------------------------------
    # Low-level YTMusic wrappers
    # ------------------------------------------------------------------

    def _get_watch_playlist(self, video_id: str, limit: int = 20, radio: bool = False) -> dict:
        for attempt_radio in ([True, False] if radio else [False]):
            try:
                return self.yt.get_watch_playlist(videoId=video_id, limit=limit, radio=attempt_radio)
            except Exception as exc:
                logger.warning(
                    "get_watch_playlist radio=%s failed for %s: %s",
                    attempt_radio, video_id, exc,
                )
        return {"tracks": []}

    def _get_song(self, video_id: str) -> dict:
        return self.yt.get_song(video_id)

    def _search(self, query: str, filter_type: str = "songs", limit: int = 3) -> list:
        return self.yt.search(query, filter=filter_type, limit=limit)

    # ------------------------------------------------------------------
    # Suggestions (async — cached)
    # ------------------------------------------------------------------

    async def get_suggestions(self, query: str) -> List[str]:
        """Return deduplicated search-suggestion strings, cached for 5 minutes."""
        cache_key = make_key("suggestions", _query_hash(query))
        cached = await self._cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache HIT get_suggestions query='%s'", query)
            return cached

        try:
            loop = asyncio.get_running_loop()
            raw = await loop.run_in_executor(None, self.yt.get_search_suggestions, query)
            result = _clean_suggestions(raw)
        except Exception as exc:
            logger.warning("Suggestions failed for '%s': %s", query, exc)
            return []

        await self._cache.set(cache_key, result, settings.redis_suggestions_ttl)
        return result

    # ------------------------------------------------------------------
    # Result processing
    # ------------------------------------------------------------------

    def process_results(
        self,
        results: list,
        result_type: str,
        filter_title: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Convert raw ytmusicapi results into the standard track dict format,
        detect labels (Official / Remix / Live / …), compute sort weight,
        and optionally exclude a title from the output.
        """
        if not results:
            return []

        processed: List[Dict[str, Any]] = []

        for t in results:
            title = t.get("title", "")
            if not title:
                continue
            if filter_title and title.lower() == filter_title:
                continue

            video_id = t.get("videoId", "")
            if not video_id:
                continue

            artists = t.get("artists", [])
            artist_name = artists[0]["name"] if artists else ""

            title_lower = title.lower()
            labels: List[str] = []
            if any(
                x in title_lower
                for x in [
                    "official video",
                    "official music video",
                    "(official video)",
                    "official audio",
                ]
            ):
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

            weight = 0
            if "Official" in labels:
                weight += 10
            if (
                result_type == "song"
                and t.get("type") == "MUSIC_VIDEO_TYPE_OFFICIAL_RELEASE"
            ):
                weight += 5

            thumbnail_url = _best_thumbnail(
                t.get("thumbnails", t.get("thumbnail", []))
            )
            if not thumbnail_url:
                thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

            processed.append(
                {
                    "title": title,
                    "artist": artist_name,
                    "videoId": video_id,
                    "music_url": f"https://music.youtube.com/watch?v={video_id}",
                    "thumbnail": thumbnail_url,
                    "type": result_type,
                    "labels": labels,
                    "weight": weight,
                }
            )

        processed.sort(key=lambda x: x["weight"], reverse=True)
        return processed

    # ------------------------------------------------------------------
    # Lyrics
    # ------------------------------------------------------------------

    def fetch_lyrics(
        self,
        title: str,
        artist: Optional[str] = None,
        browseId: Optional[str] = None,
        delay: float = 0.5,
    ) -> dict:
        """
        Fetch lyrics using a two-source waterfall:
          1. YouTube Music (free, using browseId when available)
          2. RapidAPI / Musixmatch (requires RAPIDAPI_KEY env var)
        """
        if browseId:
            try:
                logger.debug("Fetching YT lyrics browseId=%s", browseId)
                data = self.yt.get_lyrics(browseId)
                if data and "lyrics" in data:
                    return {
                        "status": 200,
                        "source": "YT",
                        "data": {
                            "lyrics": data["lyrics"],
                            "provider": data.get("source", "YouTube Music"),
                        },
                    }
            except Exception as exc:
                logger.warning("YT lyrics failed browseId=%s: %s", browseId, exc)

        if not settings.rapidapi_key:
            return {
                "status": 404,
                "error": "No lyrics found (YT failed, RAPIDAPI_KEY not set)",
            }

        params: Dict[str, str] = {"terms": title}
        if artist:
            params["artist"] = artist

        headers = {
            "x-rapidapi-key": settings.rapidapi_key,
            "x-rapidapi-host": settings.rapidapi_host,
        }

        time.sleep(delay)

        try:
            logger.debug("RapidAPI lyrics fallback title='%s'", title)
            resp = requests.get(
                settings.rapidapi_url,
                headers=headers,
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "status": data.get("status", resp.status_code),
                "data": data.get("data", data),
                "source": "RapidAPI",
            }
        except requests.HTTPError as exc:
            logger.error("RapidAPI HTTP error: %s", exc)
            return {"status": 502, "error": str(exc)}
        except Exception as exc:
            logger.error("RapidAPI unexpected error: %s", exc)
            return {"status": 500, "error": str(exc)}

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def perform_search(
        self,
        query: str,
        limit: int = 30,
        nextPlay: bool = False,
        maxVol: int = 100,
        music_type: str = "songs",
        videoId: Optional[str] = None,
        refresh: bool = False,
    ) -> Dict[str, Any]:
        from ..services.connection_manager import manager

        # Stateful operations bypass cache — they depend on current queue state.
        use_cache = not nextPlay and not refresh
        cache_key = make_key("search", _query_hash(query), limit)

        if use_cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                logger.debug("Cache HIT perform_search query='%s'", query)
                return await self._build_search_context(
                    query, cached["song_tracks"], cached["video_tracks"], limit, maxVol, music_type
                )

        target_id: Optional[str] = None
        exclude_title: Optional[str] = None

        if refresh and app_state.out_tracks:
            first = app_state.out_tracks[0]
            target_id = first.get("videoId")
            query = first.get("title", query)
            exclude_title = query.lower()
        elif nextPlay:
            target_id = videoId or find_video_id(app_state.out_tracks, query)
            exclude_title = query.lower()
            if target_id:
                await manager.broadcast(
                    {
                        "type": "play",
                        "data": {
                            "videoId": target_id,
                            "title": query,
                            "timestamp": 20,
                        },
                    }
                )

        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=2) as pool:
            song_future = pool.submit(self._search, query, "songs", limit)
            video_future = pool.submit(self._search, query, "videos", limit)
            song_raw, video_raw = await asyncio.gather(
                loop.run_in_executor(None, song_future.result),
                loop.run_in_executor(None, video_future.result),
            )

        song_tracks = self.process_results(song_raw, "song", filter_title=exclude_title)
        video_tracks = self.process_results(video_raw, "video", filter_title=exclude_title)

        if nextPlay or refresh:
            if not target_id:
                target_id = (
                    song_tracks[0]["videoId"] if song_tracks
                    else video_tracks[0]["videoId"] if video_tracks
                    else None
                )
            song_tracks = self._reorder_for_selection(song_tracks, target_id, query, refresh)
            video_tracks = self._reorder_for_selection(video_tracks, target_id, query, refresh)

        if use_cache:
            await self._cache.set(
                cache_key,
                {"song_tracks": song_tracks, "video_tracks": video_tracks},
                settings.redis_search_ttl,
            )
            logger.debug("Cache SET perform_search query='%s' ttl=%ds", query, settings.redis_search_ttl)

        return await self._build_search_context(
            query, song_tracks, video_tracks, limit, maxVol, music_type
        )

    async def _build_search_context(
        self,
        query: str,
        song_tracks: List[Dict],
        video_tracks: List[Dict],
        limit: int,
        maxVol: int,
        music_type: str,
    ) -> Dict[str, Any]:
        """Assemble final context, update app_state, and sync player context."""
        new_tracks = song_tracks + video_tracks
        for idx, t in enumerate(new_tracks):
            t["index"] = idx

        app_state.out_tracks.clear()
        app_state.out_tracks.extend(new_tracks)

        context = {
            "query": query,
            "tracks": app_state.out_tracks,
            "video_tracks": video_tracks,
            "song_tracks": song_tracks,
            "recLimit": limit,
            "maxVol": maxVol,
            "music_type": music_type,
        }
        await self._sync_player_context(context)
        return context

    def _reorder_for_selection(
        self,
        tracks: List[Dict],
        target_id: Optional[str],
        query: str,
        is_refresh: bool,
    ) -> List[Dict]:
        """Place the selected track first, shuffle the rest."""
        if not tracks:
            return []

        q_lower = query.lower()
        playing = None
        others: List[Dict] = []

        if target_id:
            for t in tracks:
                if t.get("videoId") == target_id:
                    playing = t
                else:
                    others.append(t)
        else:
            others = list(tracks)

        if not playing:
            for i, t in enumerate(others):
                if q_lower in t.get("title", "").lower():
                    playing = others.pop(i)
                    break

        if not playing and others and not is_refresh:
            playing = others.pop(0)

        matches = [t for t in others if q_lower in t.get("title", "").lower()]
        non_matches = [t for t in others if t not in matches]

        random.shuffle(matches)
        random.shuffle(non_matches)

        final: List[Dict] = []
        if playing and not is_refresh:
            final.append(playing)
        final.extend(non_matches)
        final.extend(matches)
        return final

    # ------------------------------------------------------------------
    # Play + populate (smart play flow)
    # ------------------------------------------------------------------

    async def play_and_populate(
        self,
        video_id: str,
        title: str,
        limit: int = 30,
        maxVol: int = 100,
        music_type: str = "songs",
        dj_mode: bool = True,
    ) -> Dict[str, Any]:
        """
        1. Immediately broadcast a `play` command to the Player.
        2. Fire radio logic in the background to populate the queue.
        dj_mode=True: timestamp derived from heatmap peak. False: default 20s.
        """
        from ..services.connection_manager import player_broadcaster, webapp_broadcaster

        heatmap_data = await self._get_heatmap_data(video_id)
        peaks = heatmap_data.get("peaks", [])
        raw_heatmap = heatmap_data.get("heatmap", [])
        # print(f"DEBUG: play_and_populate video_id={video_id} peaks={peaks}, raw_heatmap_length={len(raw_heatmap)}")
        if dj_mode and peaks:
            ts = int(peaks[0]["midpoint"]) - 7
            timestamp = ts if ts >= 0 else 20
        else:
            timestamp = 20

        # Broadcast compact heatmap to controllers for visualization.
        # Send only the values array + step size — avoids sending start_time/end_time
        # for every segment (~9 KB → ~800 bytes), preventing EAGAIN on the socket buffer.
        if raw_heatmap:
            print(f"DEBUG: broadcasting heatmap for video_id={video_id} segments and {len(peaks)} peaks")
            try:
                step = round(raw_heatmap[0]["end_time"] - raw_heatmap[0]["start_time"], 3)
                heatmap_data = {
                    "videoId": video_id,
                    "values": [round(s["value"], 3) for s in raw_heatmap],
                    "step": step,
                    "peaks": [round(p["midpoint"], 1) for p in peaks],}
                
            except Exception as exc:
                print(f"DEBUG: Heatmap broadcast failed for {video_id}: {peaks}")
                logger.warning("Heatmap broadcast failed for %s: %s", video_id, exc)

        radio_result = await self.start_radio(video_id=video_id, limit=limit)

        context = {
            "query": title,
            "tracks": app_state.out_tracks,
            "video_tracks": radio_result.get("video_tracks", []),
            "song_tracks": radio_result.get("song_tracks", []),
            "recLimit": limit,
            "maxVol": maxVol,
            "music_type": music_type,
        }
        await self._sync_player_context(context)
        context["timestamp"] = timestamp
        context["heatmap_data"] = heatmap_data
        return context

    # ------------------------------------------------------------------
    # Radio
    # ------------------------------------------------------------------

    async def start_radio(
        self, video_id: str, limit: int = 50
    ) -> Dict[str, Any]:
        """
        Build a radio playlist from *video_id*.

        Resolves the seed to its Official Music Video and audio counterparts,
        then fetches two watch playlists in parallel for maximum variety.
        """
        cache_key = make_key("radio", video_id, limit)
        cached = await self._cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache HIT start_radio video_id=%s", video_id)
            return await self._build_radio_context(
                cached["song_tracks"], cached["video_tracks"], limit
            )

        loop = asyncio.get_running_loop()

        def _resolve_ids(original_id: str) -> Dict[str, str]:
            ids = {"audio": original_id, "video": original_id}
            try:
                metadata = self._get_song(original_id)
                details = metadata.get("videoDetails", {})
                title = details.get("title", "")
                artist = details.get("author", "")
                video_results = self._search(
                    f"{title} {artist} official music video", "videos", 1
                )
                audio_results = self._search(
                    f"{title} {artist} official audio song", "songs", 1
                )
                if video_results:
                    ids["video"] = video_results[0].get("videoId") or original_id
                if audio_results:
                    ids["audio"] = audio_results[0].get("videoId") or original_id
            except Exception as exc:
                logger.warning("ID resolution failed for %s: %s", original_id, exc)
            return ids

        def _process_playlist(raw_list: list, music_type: str, label: str) -> List[Dict]:
            processed: List[Dict] = []
            for t in raw_list:
                vid = t.get("videoId")
                if not vid:
                    continue
                title = t.get("title", "")
                artists = t.get("artists", [])
                artist_name = artists[0]["name"] if artists else ""
                thumb_url = _best_thumbnail(
                    t.get("thumbnail", t.get("thumbnails", []))
                )
                title_lower = title.lower()
                labels = [label]
                if any(x in title_lower for x in ["official video", "music video"]):
                    labels.append("Official")
                processed.append(
                    {
                        "title": title,
                        "artist": artist_name,
                        "videoId": vid,
                        "music_url": f"https://music.youtube.com/watch?v={vid}",
                        "thumbnail": thumb_url,
                        "type": music_type,
                        "labels": labels,
                        "weight": 10 if "Official" in labels else 5,
                    }
                )
            return processed

        ids = await loop.run_in_executor(None, _resolve_ids, video_id)
        video_seed, audio_seed = ids["video"], ids["audio"]

        raw_video, raw_audio = await asyncio.gather(
            loop.run_in_executor(
                None, self._get_watch_playlist, video_seed, limit, True
            ),
            loop.run_in_executor(
                None, self._get_watch_playlist, audio_seed, limit, True
            ),
        )

        video_tracks = _process_playlist(
            raw_video.get("tracks", []), "video", "Video Mix"
        )
        song_tracks = _process_playlist(
            raw_audio.get("tracks", []), "song", "Radio Mix"
        )

        await self._cache.set(
            cache_key,
            {"song_tracks": song_tracks, "video_tracks": video_tracks},
            settings.redis_radio_ttl,
        )
        logger.debug("Cache SET start_radio video_id=%s ttl=%ds", video_id, settings.redis_radio_ttl)

        return await self._build_radio_context(song_tracks, video_tracks, limit)

    async def _build_radio_context(
        self,
        song_tracks: List[Dict],
        video_tracks: List[Dict],
        limit: int,
    ) -> Dict[str, Any]:
        """Assemble final context, update app_state, and sync player context."""
        final_list = song_tracks + video_tracks
        for i, t in enumerate(final_list):
            t["index"] = i

        app_state.out_tracks.clear()
        app_state.out_tracks.extend(final_list)

        context = {
            "query": "Radio Mix",
            "tracks": app_state.out_tracks,
            "song_tracks": song_tracks,
            "video_tracks": video_tracks,
            "recLimit": limit,
            "maxVol": app_state.player_context.get("maxVol", 100),
            "status": "success",
        }
        await self._sync_player_context(context)
        return context

    # ------------------------------------------------------------------
    # Heatmap peaks
    # ------------------------------------------------------------------

    async def _get_heatmap_data(self, video_id: str) -> Dict[str, Any]:
        """
        Fetch and cache the full YouTube heatmap for *video_id*.

        Cached payload: {"heatmap": [raw segments], "peaks": [detected peaks]}
        This lets callers access both the raw engagement curve (for plotting)
        and the peak timestamps (for DJ seek) from a single Redis entry.
        """
        cache_key = make_key("heatmap", video_id)
        cached = await self._cache.get(cache_key)
        if cached is not None and isinstance(cached, dict):
            logger.debug("Cache HIT _get_heatmap_data video_id=%s", video_id)
            return cached

        url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts = {"quiet": True, "skip_download": True}

        def _fetch() -> Optional[List[Dict]]:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info.get("heatmap")

        loop = asyncio.get_running_loop()
        try:
            raw_heatmap = await loop.run_in_executor(None, _fetch)
        except Exception as exc:
            logger.warning("yt-dlp heatmap fetch failed for %s: %s", video_id, exc)
            return {"heatmap": [], "peaks": []}

        if not raw_heatmap:
            return {"heatmap": [], "peaks": []}

        peaks = _find_peaks(raw_heatmap)
        data = {"heatmap": raw_heatmap, "peaks": peaks}

        await self._cache.set(cache_key, data, settings.redis_heatmap_ttl)
        logger.debug("Cache SET heatmap video_id=%s segments=%d peaks=%d ttl=%ds",
                     video_id, len(raw_heatmap), len(peaks), settings.redis_heatmap_ttl)
        return data

    async def get_heatmap_peaks(
        self,
        video_id: str,
        min_value: float = 0.5,
        min_gap_seconds: float = 30.0,
        window: int = 3,
    ) -> List[Dict]:
        """
        Return heatmap peaks for *video_id* sorted by engagement (highest first).

        Uses _get_heatmap_data for the cached raw heatmap, then re-computes
        peaks if non-default params are passed (no extra HTTP call needed).
        Each peak has: start_time, end_time, value, midpoint.
        """
        data = await self._get_heatmap_data(video_id)
        raw = data.get("heatmap", [])
        if not raw:
            return []
        # Default params → return cached peaks; custom params → recompute from raw
        using_defaults = (min_value == 0.5 and min_gap_seconds == 30.0 and window == 3)
        if using_defaults:
            return data.get("peaks", [])
        return _find_peaks(raw, min_value, min_gap_seconds, window)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _sync_player_context(self, context: Dict[str, Any]) -> None:
        """
        Keep app_state.player_context in sync after every operation, and
        persist it to Redis so the queue survives a server restart.

        The `tracks` key inside context is a live reference to app_state.out_tracks;
        deepcopy ensures the stored snapshot is independent of future mutations.
        """
        app_state.player_context.clear()
        app_state.player_context.update(copy.deepcopy(context))

        await self._cache.set(
            make_key("player", "context"),
            app_state.player_context,
            settings.redis_player_ttl,
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
music_service = MusicService()
