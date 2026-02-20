from ytmusicapi import YTMusic
import json
import random
import asyncio
import concurrent.futures
from datetime import datetime
from typing import List, Dict

# ═══════════════════════════════════════════════════════════════════════════
# ASYNC INDIAN MUSIC RECOMMENDATION SYSTEM (2000-2025)
# Year-Based Top Songs Approach (No Artist/Song Names)
# ═══════════════════════════════════════════════════════════════════════════

class AsyncIndianMusicRecommender:
    """
    Distribution:
    - 65% Bollywood (2000-2025)
    - 15% Punjabi 
    - 5% Haryanvi
    - 15% Other Indie (Regional, Independent Artists, Pop)
    
    Era Coverage: 2000-2025 (25 years of hits)
    Uses year-based "top songs" queries instead of artist names
    """
    
    def __init__(self, max_workers=10):
        self.yt = YTMusic()
        self.max_workers = max_workers
        self.music_database = {
            'bollywood_2000s': [],
            'bollywood_2010s': [],
            'bollywood_2020s': [],
            'punjabi': [],
            'haryanvi': [],
            'indie_regional': []
        }
        self.current_year = 2025
    
    def _search_query(self, query: str, limit: int = 4) -> List[Dict]:
        """Single search query (blocking, to be run in thread pool)"""
        try:
            results = self.yt.search(query, filter="songs", limit=limit)
            songs = []
            for song in results:
                # Extract thumbnail safely (Essential for UI)
                thumbnails = song.get("thumbnails", [])
                thumbnail_url = thumbnails[-1]["url"] if thumbnails else ""
                
                # Extract artist safely
                artists = song.get('artists', [])
                artist_name = 'Various'
                if artists:
                     artist_name = artists[0]['name']

                songs.append({
                    'title': song.get('title'),
                    'artist': artist_name,
                    'videoId': song.get('videoId'),
                    'thumbnail': thumbnail_url,
                    'music_url': f"https://music.youtube.com/watch?v={song.get('videoId')}"
                })
            return songs
        except Exception as e:
            print(f"  ✗ Error with '{query[:40]}...': {e}")
            return []
    
    async def _async_search_queries(self, queries: List[tuple], category: str, era: str = None) -> List[Dict]:
        """
        Async wrapper to run multiple search queries in parallel
        queries: List of (query_string, limit) tuples
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Create futures for all queries
            futures = [
                loop.run_in_executor(executor, self._search_query, query, limit)
                for query, limit in queries
            ]
            
            # Wait for all to complete
            results = await asyncio.gather(*futures)
        
        # Flatten results and add metadata
        all_songs = []
        for i, songs in enumerate(results):
            # query_name = queries[i][0]
            for song in songs:
                song['category'] = category
                song['era'] = era if era else 'multi'
                song['year_range'] = self._get_year_range(category, era)
                all_songs.append(song)
            
            # if songs:
            #     print(f"  ✓ Added: {query_name[:50]}... ({len(songs)} songs)")
        
        return all_songs
    
    def _get_year_range(self, category: str, era: str) -> str:
        """Get year range based on category and era"""
        if era == '2000s':
            return '2000-2009'
        elif era == '2010s':
            return '2010-2019'
        elif era == '2020s':
            return '2020-2025'
        elif category == 'haryanvi':
            return '2015-2025'
        elif category == 'indie_regional':
            return '2010-2025'
        else:
            return '2000-2025'
    
    async def build_bollywood_2000s(self):
        """Build Bollywood collection from 2000-2009 using year-based queries"""
        # print("\n🎬 Building Bollywood 2000s Collection...")
        
        queries = [
            # Year-based top songs
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
            # Genre + Era based
            ("bollywood romantic songs 2000s", 4),
            ("bollywood dance songs 2000-2009", 4),
            ("hindi party songs 2000s decade", 4),
        ]
        
        songs = await self._async_search_queries(queries, 'bollywood', '2000s')
        self.music_database['bollywood_2000s'] = songs
        # print(f"  📊 Total 2000s Bollywood: {len(songs)}\n")
        return songs
    
    async def build_bollywood_2010s(self):
        """Build Bollywood collection from 2010-2019 using year-based queries"""
        # print("\n🎬 Building Bollywood 2010s Collection...")
        
        queries = [
            # Year-based top songs
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
            # Genre + Era based
            ("bollywood romantic songs 2010s", 4),
            ("bollywood dance songs 2010-2019", 4),
            ("hindi party songs 2010s decade", 4),
            ("bollywood wedding songs 2010s", 4),
        ]
        
        songs = await self._async_search_queries(queries, 'bollywood', '2010s')
        self.music_database['bollywood_2010s'] = songs
        # print(f"  📊 Total 2010s Bollywood: {len(songs)}\n")
        return songs
    
    async def build_bollywood_2020s(self):
        """Build Bollywood collection from 2020-2025 using year-based queries"""
        # print("\n🎬 Building Bollywood 2020s Collection...")
        
        queries = [
            # Year-based top songs
            ("top bollywood songs 2020", 5),
            ("best hindi songs 2021", 5),
            ("superhit bollywood songs 2022", 5),
            ("top hindi songs 2023", 5),
            ("best bollywood hits 2024", 5),
            ("top bollywood songs 2025", 5),
            # Genre + Era based
            ("bollywood romantic songs 2020s", 4),
            ("bollywood dance songs 2020-2025", 4),
            ("hindi party songs 2020s", 4),
            ("bollywood trending songs 2024", 4),
            ("latest bollywood hits 2025", 4),
        ]
        
        songs = await self._async_search_queries(queries, 'bollywood', '2020s')
        self.music_database['bollywood_2020s'] = songs
        # print(f"  📊 Total 2020s Bollywood: {len(songs)}\n")
        return songs
    
    async def build_punjabi_collection(self):
        """Build Punjabi collection using genre + year queries"""
        # print("\n🎤 Building Punjabi Collection...")
        
        queries = [
            # Year-based Punjabi hits
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
            # Genre-based
            ("punjabi party songs latest", 3),
            ("punjabi romantic songs best", 3),
            ("punjabi bhangra songs top", 3),
        ]
        
        songs = await self._async_search_queries(queries, 'punjabi')
        self.music_database['punjabi'] = songs
        # print(f"  📊 Total Punjabi: {len(songs)}\n")
        return songs
    
    async def build_haryanvi_collection(self):
        """Build Haryanvi collection using genre + year queries"""
        # print("\n🔊 Building Haryanvi Collection...")
        
        queries = [
            # Year-based Haryanvi hits
            ("top haryanvi songs 2020", 3),
            ("best haryanvi songs 2021", 3),
            ("superhit haryanvi songs 2022", 3),
            ("top haryanvi songs 2023", 3),
            ("best haryanvi hits 2024", 3),
            # Genre-based
            ("haryanvi dance songs latest", 2),
            ("haryanvi dj songs best", 2),
            ("haryanvi bass songs top", 2),
        ]
        
        songs = await self._async_search_queries(queries, 'haryanvi')
        self.music_database['haryanvi'] = songs
        # print(f"  📊 Total Haryanvi: {len(songs)}\n")
        return songs
    
    async def build_indie_regional_collection(self):
        """Build Indie & Regional collection using genre queries"""
        # print("\n🎸 Building Indie & Regional Collection...")
        
        queries = [
            # Indie Pop/Rock year-based
            ("top indian indie songs 2020", 3),
            ("best indian indie songs 2021", 3),
            ("top indian indie songs 2022", 3),
            ("best indian indie songs 2023", 3),
            ("top indian indie songs 2024", 3),
            # Genre-based indie
            ("indian indie pop songs best", 2),
            ("indian indie rock songs top", 2),
            ("indian electronic music best", 2),
            # Regional hits
            ("top tamil songs 2023", 2),
            ("best tamil songs 2024", 2),
            ("top telugu songs 2023", 2),
            ("best telugu songs 2024", 2),
            # Hip-hop/Rap
            ("indian hip hop songs best", 2),
            ("indian rap songs top 2024", 2),
        ]
        
        songs = await self._async_search_queries(queries, 'indie_regional')
        self.music_database['indie_regional'] = songs
        # print(f"  📊 Total Indie/Regional: {len(songs)}\n")
        return songs
    
    async def build_all_collections(self):
        """Build all collections in parallel"""
        print("\n⚡ Building ALL collections in parallel (Background Task)...\n")
        import time
        start_time = time.time()
        
        # Run all collection builders in parallel
        await asyncio.gather(
            self.build_bollywood_2000s(),
            self.build_bollywood_2010s(),
            self.build_bollywood_2020s(),
            self.build_punjabi_collection(),
            self.build_haryanvi_collection(),
            self.build_indie_regional_collection(),
        )
        
        end_time = time.time()
        elapsed = end_time - start_time
        
        total_songs = sum(len(songs) for songs in self.music_database.values())
        
        print(f"\n{'='*80}")
        print(f"⚡ ALL COLLECTIONS BUILT IN {elapsed:.2f} SECONDS")
        print(f"📊 Total songs collected: {total_songs}")
        print(f"{'='*80}\n")
    
    def generate_dynamic_playlist(self, total_songs=50):
        """
        Generate a 50-song dynamic playlist
        """
        # Calculate distribution
        bollywood_count = int(total_songs * 0.65)
        punjabi_count = int(total_songs * 0.15)
        haryanvi_count = int(total_songs * 0.05)
        indie_count = int(total_songs * 0.15)
        
        playlist = []
        
        # Bollywood - distribute across eras (balanced)
        all_bollywood = (
            self.music_database['bollywood_2000s'] +
            self.music_database['bollywood_2010s'] +
            self.music_database['bollywood_2020s']
        )
        
        if all_bollywood:
            # Try to get equal representation from each era
            songs_per_era = bollywood_count // 3
            
            for era_key in ['bollywood_2000s', 'bollywood_2010s', 'bollywood_2020s']:
                era_songs = self.music_database[era_key]
                if era_songs:
                    selected = random.sample(
                        era_songs,
                        min(songs_per_era, len(era_songs))
                    )
                    playlist.extend(selected)
            
            # Fill remaining bollywood slots if needed
            current_bolly = len([s for s in playlist if s['category'] == 'bollywood'])
            remaining = bollywood_count - current_bolly
            if remaining > 0 and all_bollywood:
                available = [s for s in all_bollywood if s not in playlist]
                if available:
                    additional = random.sample(
                        available,
                        min(remaining, len(available))
                    )
                    playlist.extend(additional)
        
        # Add Punjabi
        if self.music_database['punjabi']:
            playlist.extend(random.sample(
                self.music_database['punjabi'],
                min(punjabi_count, len(self.music_database['punjabi']))
            ))
        
        # Add Haryanvi
        if self.music_database['haryanvi']:
            playlist.extend(random.sample(
                self.music_database['haryanvi'],
                min(haryanvi_count, len(self.music_database['haryanvi']))
            ))
        
        # Add Indie/Regional
        if self.music_database['indie_regional']:
            playlist.extend(random.sample(
                self.music_database['indie_regional'],
                min(indie_count, len(self.music_database['indie_regional']))
            ))
        
        # Shuffle for variety
        random.shuffle(playlist)
        
        # Trim to exactly total_songs
        playlist = playlist[:total_songs]
        
        return playlist
    
    def save_database(self, filename='indian_music_2000_2025.json'):
        """Save the entire music database"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.music_database, f, ensure_ascii=False, indent=2)
        # print(f"✅ Database saved to {filename}")
