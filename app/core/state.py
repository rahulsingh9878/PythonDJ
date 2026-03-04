import time
from typing import List, Dict, Any

# Application State
server_start_time: float = time.time()
out_tracks: List[Dict[str, Any]] = []
default_context: Dict[str, Any] = {"recLimit": 30, "maxVol": 100, "isMuted": False}
next_song_dt: Dict[str, Any] = {"title": None, "videoId": None, "timestamp": 20}
RESULT_CACHE: Dict[str, Any] = {}
