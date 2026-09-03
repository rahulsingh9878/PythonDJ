"""
Name-based lookup for WLED's effect (FX) and palette catalogs, plus the
color-gradient data used to render palette preview swatches in the UI.

The catalog data started as a one-time snapshot fetched from the device
itself (`GET /json/effects`, `/json/palettes`, `/json/fxdata`, `/json/palx`),
committed under `catalog_data/`, so the club-sync effect rotation and the
palette/effect pickers can all reference effects by human name instead of
hardcoding index numbers that could shift across firmware versions, and the
palette picker can show real colors without duplicating WLED's own color
math.

That file is only ever read once per Redis cache lifetime: `load()` checks
Redis first, and only falls back to the committed snapshot on a cache miss
(first boot, a schema bump, or after the TTL expires), immediately
re-seeding Redis so every other call — other gunicorn workers included —
hits cache, never disk. Call `load()` once at app startup before anything
else in this package is used.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...core.cache import CacheBackend, make_key

logger = logging.getLogger(__name__)

_CATALOG_DIR = Path(__file__).parent / "catalog_data"
_CACHE_KEY = make_key("wled", "catalog")
_CACHE_TTL = 30 * 24 * 3600  # 30 days — this only changes on a WLED firmware upgrade
_SCHEMA_VERSION = 2  # bump whenever the cached shape changes, to auto-invalidate old entries

EFFECTS: List[str] = []
PALETTES: List[str] = []
FXDATA: List[str] = []
PALX: Dict[str, Any] = {}  # palette index (str) -> [[pos,r,g,b], ...] or special marker list

_effect_by_name: Dict[str, int] = {}
_palette_by_name: Dict[str, int] = {}


def _read_from_disk() -> Dict[str, Any]:
    def _load_one(name: str):
        with open(_CATALOG_DIR / f"{name}.json") as f:
            return json.load(f)

    return {
        "version": _SCHEMA_VERSION,
        "effects": _load_one("effects"),
        "palettes": _load_one("palettes"),
        "fxdata": _load_one("fxdata"),
        "palx": _load_one("palx"),
    }


def _apply(data: Dict[str, Any]) -> None:
    global EFFECTS, PALETTES, FXDATA, PALX, _effect_by_name, _palette_by_name
    EFFECTS = data["effects"]
    PALETTES = data["palettes"]
    FXDATA = data["fxdata"]
    PALX = data["palx"]
    _effect_by_name = {name.lower(): i for i, name in enumerate(EFFECTS)}
    _palette_by_name = {name.lower(): i for i, name in enumerate(PALETTES)}


async def load(cache: CacheBackend) -> None:
    """Populate the in-memory catalog from Redis, seeding it from disk on a miss."""
    cached = await cache.get(_CACHE_KEY)
    if cached is not None and cached.get("version") == _SCHEMA_VERSION:
        _apply(cached)
        logger.info(
            "WLED: catalog loaded from cache (%d effects, %d palettes)", len(EFFECTS), len(PALETTES)
        )
        return

    data = _read_from_disk()
    _apply(data)
    await cache.set(_CACHE_KEY, data, ttl=_CACHE_TTL)
    logger.info(
        "WLED: catalog loaded from disk snapshot and cached (%d effects, %d palettes)",
        len(EFFECTS), len(PALETTES),
    )


def is_audio_reactive(index: int) -> bool:
    """
    Whether effect *index* reacts to audio input — WLED's own fxdata marks
    these with a `si=` (sound input) default, e.g. Freqwave, Gravimeter,
    DJ Light. Not encoded as a dedicated flag, so this is the same signal
    WLED's own UI effectively relies on.
    """
    raw = FXDATA[index] if 0 <= index < len(FXDATA) else ""
    return "si=" in raw


def usable_effects() -> List[Dict[str, Any]]:
    """Effect name/audio-reactive pairs for display/picking — excludes unassigned "RSVD" slots."""
    return [
        {"name": name, "audio": is_audio_reactive(i)}
        for i, name in enumerate(EFFECTS)
        if name != "RSVD"
    ]


def audio_reactive_indices() -> List[int]:
    """Every audio-reactive effect index (RSVD-excluded) — the pool the club-sync rotation picks from."""
    return [i for i, name in enumerate(EFFECTS) if name != "RSVD" and is_audio_reactive(i)]


def effect_index(name: str) -> Optional[int]:
    idx = _effect_by_name.get(name.lower())
    if idx is None:
        logger.warning("WLED: unknown effect name %r, not in catalog", name)
    return idx


def palette_index(name: str) -> Optional[int]:
    idx = _palette_by_name.get(name.lower())
    if idx is None:
        logger.warning("WLED: unknown palette name %r, not in catalog", name)
    return idx


def effect_controls(index: int) -> Dict[str, Any]:
    """
    Which of an effect's sliders (Speed, Intensity, Custom 1-3) are actually
    meaningful for it, with labels and suggested defaults, parsed from its
    `/json/fxdata` string (the same data WLED's own UI reads to decide which
    sliders to draw and how to caption them).

    Format (`;`-separated): "sxLabel,ixLabel,c1Label,c2Label,c3Label,...;
    colorLabels;paletteLabel;flags;key=val,key=val,...". A label of "!"
    means "show with the generic name"; "" (present but empty) means "hide
    this slider"; a missing trailing slot defaults to shown for sx/ix
    (they're near-universal) but hidden for c1-c3 (genuinely optional).
    """
    raw = FXDATA[index] if 0 <= index < len(FXDATA) else ""
    parts = raw.split(";")[0].split(",") if raw else []

    def _label(i: int, default: str, shown_if_missing: bool) -> Optional[str]:
        if i < len(parts):
            p = parts[i]
            if p == "":
                return None
            return default if p == "!" else p
        return default if shown_if_missing else None

    labels = {
        "sx": _label(0, "Speed", True),
        "ix": _label(1, "Intensity", True),
        "c1": _label(2, "Custom 1", False),
        "c2": _label(3, "Custom 2", False),
        "c3": _label(4, "Custom 3", False),
    }

    defaults: Dict[str, int] = {}
    kv_segment = raw.split(";")[4] if raw.count(";") >= 4 else ""
    for pair in kv_segment.split(","):
        if "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        key = key.strip()
        if key in labels and value.strip().lstrip("-").isdigit():
            defaults[key] = int(value)

    return {"labels": labels, "defaults": defaults}


def palette_color_markers(index: int) -> Optional[List[str]]:
    """
    For the "structural" palettes (Random Cycle, Color 1, Colors 1&2, Color
    Gradient, Colors Only) that render from the segment's own colors rather
    than a fixed gradient, `/json/palx` gives a marker list ("r" = random,
    "c1"/"c2"/"c3" = that color slot) instead of [pos,r,g,b] stops. Returns
    that marker list so the frontend can build a live preview from whatever
    colors are actually picked; `None` for palettes with a real gradient.
    """
    entry = PALX.get(str(index))
    if entry and not isinstance(entry[0], list):
        return entry
    return None


def palette_gradient(index: int) -> str:
    """
    CSS linear-gradient() string for palette *index*'s preview swatch, built
    from the same `/json/palx` stop data WLED's own UI uses for the little
    `lstIprev` gradient divs.

    A few palettes (Random Cycle, Color 1, Colors 1&2, ...) are "structural"
    — they render from the segment's own live colors rather than a fixed
    gradient, so `/json/palx` gives marker strings ("r", "c1", ...) instead
    of [pos, r, g, b] stops for those; a neutral placeholder gradient is
    used for them since we don't track per-segment color state here.
    """
    entry = PALX.get(str(index))
    if not entry or not isinstance(entry[0], list):
        return "linear-gradient(to right, #3a3a3a, #6a6a6a, #3a3a3a)"

    stops = [f"rgb({r},{g},{b}) {round(pos / 255 * 100)}%" for pos, r, g, b in entry]
    return "linear-gradient(to right, " + ", ".join(stops) + ")"
