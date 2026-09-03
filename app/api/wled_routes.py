"""
REST endpoints for WLED club-light ambience: the heatmap-driven audio-reactive
effect rotation (see `services/wled/controller.py`), plus standalone palette,
effect, and color changes (see `services/wled/catalog.py`).
"""

import logging
import re
from typing import Dict

from fastapi import APIRouter, Body, HTTPException

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")

from ..services.wled import catalog
from ..services.wled.controller import wled_controller

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wled")


@router.post("/power/{state}")
async def set_power(state: str):
    """Turn the strip on or off. *state* is "on" or "off"."""
    if state not in ("on", "off"):
        raise HTTPException(status_code=400, detail="state must be 'on' or 'off'")
    applied = await wled_controller.set_power(state == "on")
    if not applied:
        raise HTTPException(status_code=503, detail="WLED unreachable, try again")
    return {"on": state == "on"}


@router.post("/brightness/{value}")
async def set_brightness(value: int):
    """Set overall strip brightness. *value* is 0-255."""
    if not 0 <= value <= 255:
        raise HTTPException(status_code=400, detail="value must be 0-255")
    applied = await wled_controller.set_brightness(value)
    if not applied:
        raise HTTPException(status_code=503, detail="WLED unreachable, try again")
    return {"brightness": value}


@router.post("/color/{hex_code}")
async def set_color(hex_code: str, slot: int = 0):
    """
    Set a segment color slot. *hex_code* is a 6-digit hex string (e.g.
    "ff8800" or "#ff8800"); *slot* is 0=primary, 1=secondary, 2=tertiary —
    the same "Color 1/2/3" WLED's own color wheel writes to.
    """
    match = _HEX_RE.match(hex_code)
    if not match:
        raise HTTPException(status_code=400, detail="hex_code must be 6 hex digits, e.g. 'ff8800'")
    if slot not in (0, 1, 2):
        raise HTTPException(status_code=400, detail="slot must be 0, 1, or 2")
    hex_digits = match.group(1)
    r, g, b = (int(hex_digits[i:i + 2], 16) for i in (0, 2, 4))
    applied = await wled_controller.set_color(r, g, b, slot)
    if not applied:
        raise HTTPException(status_code=503, detail="WLED unreachable, try again")
    return {"color": f"#{hex_digits}", "slot": slot}


@router.post("/sync/resume")
async def resume_sync():
    """Drop a manual effect/params override; heatmap auto-sync resumes if a song is active."""
    await wled_controller.resume_auto_sync()
    return {"resumed": True}


@router.post("/sync/{state}")
async def set_club_sync(state: str):
    """Turn the heatmap-driven club-light loop on or off. *state* is "on" or "off". Persists across songs."""
    if state not in ("on", "off"):
        raise HTTPException(status_code=400, detail="state must be 'on' or 'off'")
    await wled_controller.set_club_sync(state == "on")
    return {"sync": state == "on"}


@router.post("/peakfx/{state}")
async def set_peak_fx(state: str):
    """Turn effect/palette/color changes at song start and each heatmap peak on or off. *state* is "on" or "off"."""
    if state not in ("on", "off"):
        raise HTTPException(status_code=400, detail="state must be 'on' or 'off'")
    await wled_controller.set_peak_fx(state == "on")
    return {"peakfx": state == "on"}


@router.get("/palettes")
async def list_palettes():
    """Every palette on this device, with a CSS gradient (or color-slot markers) for preview swatches."""
    return {
        "palettes": [
            {
                "name": name,
                "gradient": catalog.palette_gradient(i),
                "markers": catalog.palette_color_markers(i),
            }
            for i, name in enumerate(catalog.PALETTES)
        ]
    }


@router.post("/palette/{palette_name}")
async def trigger_palette(palette_name: str):
    """Apply just a palette (leaves the current effect/speed untouched)."""
    if catalog.palette_index(palette_name) is None:
        raise HTTPException(status_code=404, detail=f"Unknown palette: {palette_name!r}")
    applied = await wled_controller.set_palette(palette_name)
    if not applied:
        raise HTTPException(status_code=503, detail="WLED unreachable, try again")
    return {"palette": palette_name}


@router.get("/effects")
async def list_effects():
    """Every usable effect name on this device (RSVD slots excluded)."""
    return {"effects": catalog.usable_effects()}


@router.post("/effect/{effect_name}")
async def trigger_effect(effect_name: str):
    """Apply just an effect (leaves speed/intensity/palette untouched)."""
    if catalog.effect_index(effect_name) is None:
        raise HTTPException(status_code=404, detail=f"Unknown effect: {effect_name!r}")
    applied = await wled_controller.set_effect(effect_name)
    if not applied:
        raise HTTPException(status_code=503, detail="WLED unreachable, try again")
    return {"effect": effect_name}


@router.get("/effect/{effect_name}/controls")
async def get_effect_controls(effect_name: str):
    """Which sliders (Speed/Intensity/Custom 1-3) this effect actually uses, with labels and defaults."""
    idx = catalog.effect_index(effect_name)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Unknown effect: {effect_name!r}")
    return catalog.effect_controls(idx)


_PARAM_KEYS = {"sx", "ix", "c1", "c2", "c3"}


@router.post("/params")
async def set_params(params: Dict[str, int] = Body(...)):
    """Live-tweak sx/ix/c1/c2/c3 on the current effect. Partial — only the given keys are sent."""
    if not params or not set(params).issubset(_PARAM_KEYS):
        raise HTTPException(status_code=400, detail=f"params must be a subset of {sorted(_PARAM_KEYS)}")
    applied = await wled_controller.set_params(params)
    if not applied:
        raise HTTPException(status_code=503, detail="WLED unreachable, try again")
    return {"applied": params}
