"""
Global application state.

A single `AppState` dataclass instance (`app_state`) is created at import
time and shared across the application.  All mutable state lives here so
it is easy to locate, reason about, and – in tests – replace or reset.

Usage:
    from app.core.state import app_state

    app_state.out_tracks.append(track)
    app_state.player_context["maxVol"] = 80
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class AppState:
    # Unix timestamp recorded when the server process started
    server_start_time: float = field(default_factory=time.time)

    # Flat ordered list of every track currently in the active queue.
    # Each entry is a dict produced by MusicService.process_results().
    out_tracks: List[Dict[str, Any]] = field(default_factory=list)

    # Last-known player settings (volume, mute, music type, etc.).
    # Also used as the Jinja2 template context so it doubles as "view state".
    player_context: Dict[str, Any] = field(
        default_factory=lambda: {
            "recLimit": 30,
            "maxVol": 100,
            "isMuted": False,
            "music_type": "songs",
            "query": "",
            "tracks": [],
            "video_tracks": [],
            "song_tracks": [],
        }
    )

    # Metadata of the track queued to play next (used by the player to
    # know when to start the crossfade countdown).
    next_song: Dict[str, Any] = field(
        default_factory=lambda: {
            "title": None,
            "videoId": None,
            "timestamp": 20,
        }
    )

    # Ephemeral in-process cache (currently unused but reserved for
    # caching expensive search results).
    result_cache: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Single shared instance
# ---------------------------------------------------------------------------
app_state = AppState()

# ---------------------------------------------------------------------------
# Backward-compatible aliases – existing modules import these by name.
# They point to the *same* objects inside app_state so mutations made
# through either path are immediately visible everywhere.
# ---------------------------------------------------------------------------
out_tracks = app_state.out_tracks
default_context = app_state.player_context
next_song_dt = app_state.next_song
RESULT_CACHE = app_state.result_cache
