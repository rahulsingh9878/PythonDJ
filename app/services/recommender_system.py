"""
Async Indian Music Recommendation System (2000 – 2025).

AsyncIndianMusicRecommender pre-fetches a rich music database at startup
using parallel async queries and exposes `generate_dynamic_playlist()` to
build a shuffled, genre-balanced playlist on demand.

Genre distribution (50-song default):
  - 65 % Bollywood (2000-2025, split equally across three eras)
  - 15 % Punjabi
  -  5 % Haryanvi
  - 15 % Indie / Regional
"""

import asyncio
import concurrent.futures
import logging
import random
import time
from typing import Dict, List

from ytmusicapi import YTMusic

logger = logging.getLogger(__name__)


class AsyncIndianMusicRecommender:
    """
    Builds a categorised music database via parallel YTMusic searches.

    Pass a shared *yt* instance to avoid creating a second anonymous
    YTMusic session alongside the one in MusicService.
    """

    def __init__(self, yt: YTMusic, max_workers: int = 10) -> None:
        self.yt = yt
        self.max_workers = max_workers
        self.music_database: Dict[str, List[Dict]] = {
            "bollywood_2000s": [],
            "bollywood_2010s": [],
            "bollywood_2020s": [],
            "punjabi": [],
            "haryanvi": [],
            "indie_regional": [],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _search_query(self, query: str, limit: int = 4) -> List[Dict]:
        """Blocking YTMusic search – run inside a thread-pool executor."""
        try:
            results = self.yt.search(query, filter="songs", limit=limit)
            songs: List[Dict] = []
            for song in results:
                thumbnails = song.get("thumbnails", [])
                thumbnail_url = thumbnails[-1]["url"] if thumbnails else ""
                artists = song.get("artists", [])
                artist_name = artists[0]["name"] if artists else "Various"
                video_id = song.get("videoId", "")
                songs.append(
                    {
                        "title": song.get("title", ""),
                        "artist": artist_name,
                        "videoId": video_id,
                        "thumbnail": thumbnail_url,
                        "music_url": f"https://music.youtube.com/watch?v={video_id}",
                    }
                )
            return songs
        except Exception as exc:
            logger.warning("Search failed for query '%s': %s", query[:50], exc)
            return []

    async def _run_queries(
        self,
        queries: List[tuple],
        category: str,
        era: str = "multi",
    ) -> List[Dict]:
        """
        Run *queries* in parallel using a thread-pool and annotate each
        result with category / era metadata.
        """
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers
        ) as executor:
            futures = [
                loop.run_in_executor(executor, self._search_query, q, lim)
                for q, lim in queries
            ]
            results = await asyncio.gather(*futures)

        all_songs: List[Dict] = []
        for songs in results:
            for song in songs:
                song["category"] = category
                song["era"] = era
                all_songs.append(song)
        return all_songs

    # ------------------------------------------------------------------
    # Collection builders
    # ------------------------------------------------------------------

    async def _build_bollywood_2000s(self) -> None:
        queries = [
            ("top bollywood songs 2000", 5),
            ("best hindi songs 2001", 5),
            ("superhit bollywood songs 2002", 5),
            ("top hindi songs 2003", 5),
            ("best bollywood hits 2004", 5),
            ("top bollywood songs 2005", 5),
            ("best hindi songs 2006", 5),
            ("superhit bollywood songs 2007", 5),
            ("top hindi songs 2008", 5),
            ("best bollywood hits 2009", 5),
            ("bollywood romantic songs 2000s", 4),
            ("bollywood dance songs 2000-2009", 4),
            ("hindi party songs 2000s decade", 4),
        ]
        self.music_database["bollywood_2000s"] = await self._run_queries(
            queries, "bollywood", "2000s"
        )

    async def _build_bollywood_2010s(self) -> None:
        queries = [
            ("top bollywood songs 2010", 5),
            ("best hindi songs 2011", 5),
            ("superhit bollywood songs 2012", 5),
            ("top hindi songs 2013", 5),
            ("best bollywood hits 2014", 5),
            ("top bollywood songs 2015", 5),
            ("best hindi songs 2016", 5),
            ("superhit bollywood songs 2017", 5),
            ("top hindi songs 2018", 5),
            ("best bollywood hits 2019", 5),
            ("bollywood romantic songs 2010s", 4),
            ("bollywood dance songs 2010-2019", 4),
            ("hindi party songs 2010s decade", 4),
            ("bollywood wedding songs 2010s", 4),
        ]
        self.music_database["bollywood_2010s"] = await self._run_queries(
            queries, "bollywood", "2010s"
        )

    async def _build_bollywood_2020s(self) -> None:
        queries = [
            ("top bollywood songs 2020", 5),
            ("best hindi songs 2021", 5),
            ("superhit bollywood songs 2022", 5),
            ("top hindi songs 2023", 5),
            ("best bollywood hits 2024", 5),
            ("top bollywood songs 2025", 5),
            ("bollywood romantic songs 2020s", 4),
            ("bollywood dance songs 2020-2025", 4),
            ("hindi party songs 2020s", 4),
            ("bollywood trending songs 2024", 4),
            ("latest bollywood hits 2025", 4),
        ]
        self.music_database["bollywood_2020s"] = await self._run_queries(
            queries, "bollywood", "2020s"
        )

    async def _build_punjabi(self) -> None:
        queries = [
            ("top punjabi songs 2015", 3),
            ("best punjabi songs 2016", 3),
            ("superhit punjabi songs 2017", 3),
            ("top punjabi songs 2018", 3),
            ("best punjabi hits 2019", 3),
            ("top punjabi songs 2020", 3),
            ("best punjabi songs 2021", 3),
            ("superhit punjabi songs 2022", 3),
            ("top punjabi songs 2023", 3),
            ("best punjabi hits 2024", 3),
            ("top punjabi songs 2025", 3),
            ("punjabi party songs latest", 3),
            ("punjabi romantic songs best", 3),
            ("punjabi bhangra songs top", 3),
        ]
        self.music_database["punjabi"] = await self._run_queries(
            queries, "punjabi"
        )

    async def _build_haryanvi(self) -> None:
        queries = [
            ("top haryanvi songs 2020", 3),
            ("best haryanvi songs 2021", 3),
            ("superhit haryanvi songs 2022", 3),
            ("top haryanvi songs 2023", 3),
            ("best haryanvi hits 2024", 3),
            ("haryanvi dance songs latest", 2),
            ("haryanvi dj songs best", 2),
            ("haryanvi bass songs top", 2),
        ]
        self.music_database["haryanvi"] = await self._run_queries(
            queries, "haryanvi"
        )

    async def _build_indie_regional(self) -> None:
        queries = [
            ("top indian indie songs 2020", 3),
            ("best indian indie songs 2021", 3),
            ("top indian indie songs 2022", 3),
            ("best indian indie songs 2023", 3),
            ("top indian indie songs 2024", 3),
            ("indian indie pop songs best", 2),
            ("indian indie rock songs top", 2),
            ("indian electronic music best", 2),
            ("top tamil songs 2023", 2),
            ("best tamil songs 2024", 2),
            ("top telugu songs 2023", 2),
            ("best telugu songs 2024", 2),
            ("indian hip hop songs best", 2),
            ("indian rap songs top 2024", 2),
        ]
        self.music_database["indie_regional"] = await self._run_queries(
            queries, "indie_regional"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def build_all_collections(self) -> None:
        """Fetch all six genre collections in parallel (background task)."""
        logger.info("Building music database in background…")
        start = time.perf_counter()

        await asyncio.gather(
            self._build_bollywood_2000s(),
            self._build_bollywood_2010s(),
            self._build_bollywood_2020s(),
            self._build_punjabi(),
            self._build_haryanvi(),
            self._build_indie_regional(),
        )

        elapsed = time.perf_counter() - start
        total = sum(len(v) for v in self.music_database.values())
        logger.info(
            "Music database ready – %d songs across %d categories in %.2fs",
            total,
            len(self.music_database),
            elapsed,
        )

    def generate_dynamic_playlist(self, total_songs: int = 50) -> List[Dict]:
        """
        Return a shuffled playlist of *total_songs* tracks that respects the
        genre distribution defined in the class docstring.

        Falls back gracefully if a category has fewer songs than requested.
        """
        bollywood_count = int(total_songs * 0.65)
        punjabi_count = int(total_songs * 0.15)
        haryanvi_count = int(total_songs * 0.05)
        indie_count = int(total_songs * 0.15)

        playlist: List[Dict] = []

        # Bollywood: equal share from each era
        songs_per_era = bollywood_count // 3
        for era_key in ("bollywood_2000s", "bollywood_2010s", "bollywood_2020s"):
            era_pool = self.music_database[era_key]
            if era_pool:
                playlist.extend(
                    random.sample(era_pool, min(songs_per_era, len(era_pool)))
                )

        # Fill any remaining Bollywood slots from the combined pool
        all_bollywood = (
            self.music_database["bollywood_2000s"]
            + self.music_database["bollywood_2010s"]
            + self.music_database["bollywood_2020s"]
        )
        current_bolly = sum(1 for s in playlist if s.get("category") == "bollywood")
        remaining = bollywood_count - current_bolly
        if remaining > 0 and all_bollywood:
            available = [s for s in all_bollywood if s not in playlist]
            if available:
                playlist.extend(
                    random.sample(available, min(remaining, len(available)))
                )

        # Other genres
        for key, count in (
            ("punjabi", punjabi_count),
            ("haryanvi", haryanvi_count),
            ("indie_regional", indie_count),
        ):
            pool = self.music_database[key]
            if pool:
                playlist.extend(random.sample(pool, min(count, len(pool))))

        random.shuffle(playlist)
        return playlist[:total_songs]
