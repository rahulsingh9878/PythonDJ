from typing import List, Dict, Any

# Application State
out_tracks: List[Dict[str, Any]] = []
default_context: Dict[str, Any] = {"recLimit": 30, "maxVol": 100}
next_song_dt: Dict[str, Any] = {"title": None, "videoId": None, "timestamp": 20}
RESULT_CACHE: Dict[str, Any] = {}
