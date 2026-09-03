"""
Club-light ambience: drives WLED's audio-reactive effects from a YouTube
heatmap, kept in sync with server-side playback state.

Two independent, persistent toggles shape the look:
  - Club Sync (`_club_sync_enabled`): master on/off for all heatmap-driven
    updates. When on, whichever sliders the current effect exposes
    (sx/ix/c1/c2/c3, per `catalog.effect_controls()`) are driven together
    every tick from the heatmap curve, so the look pulses with the song's
    energy — not just a speed knob.
  - Peak FX (`_peak_fx_enabled`): whether the effect/palette/color actually
    *changes* — to a new random pick from the audio-reactive pool
    (`catalog.audio_reactive_indices()`), a random palette, and a random
    vivid color — at song start and at each detected heatmap peak (the same
    peaks `music_service._find_peaks()` already computes for the DJ-mode
    seek target, passed straight through to `start()`). Off means the
    continuous param pulse above keeps running against whatever effect is
    already showing, without swapping looks.

This is the asyncio-native counterpart to the standalone `heatmap_speed.py`
CLI script in this package: same interpolation/mapping math, but run as a
background task owned by one module-level singleton (`wled_controller`) so
`music_service.play_and_populate` and the `/ws/sync` control handler can
start/pause/resume/seek/stop it without blocking the event loop.

Updates are sent over WLED's JSON WebSocket API (`ws://<ip>/ws`) rather than
its legacy `/win` HTTP query-string API: one connection is kept open for the
process lifetime (auto-reconnecting) instead of opening a fresh HTTP
connection per update.

No-ops everywhere when `settings.wled_ip` is unset, so the feature is fully
opt-in.
"""

import asyncio
import colorsys
import json
import logging
import random
import time
from typing import Any, Dict, List, Optional

import websockets

from ...core.config import settings
from . import catalog

logger = logging.getLogger(__name__)


def _value_at(buckets: List[Dict], t: float) -> float:
    """Linearly interpolate the heatmap value at time t (seconds)."""
    if t <= buckets[0]["start_time"]:
        return buckets[0]["value"]
    if t >= buckets[-1]["end_time"]:
        return buckets[-1]["value"]

    # interpolate between bucket midpoints so the curve is smooth, not stepped
    mids = [((b["start_time"] + b["end_time"]) / 2.0, b["value"]) for b in buckets]
    if t <= mids[0][0]:
        return mids[0][1]
    for (t0, v0), (t1, v1) in zip(mids, mids[1:]):
        if t0 <= t <= t1:
            f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return v0 + f * (v1 - v0)
    return mids[-1][1]


def _to_sx(value: float, lo: int, hi: int, gamma: float) -> int:
    """Map a 0..1 heatmap value to a 0-255 byte, with optional curve shaping."""
    v = max(0.0, min(1.0, value)) ** gamma
    return int(round(lo + v * (hi - lo)))


_PARAM_KEYS = ("sx", "ix", "c1", "c2", "c3")


class WledSyncController:
    """One song plays at a time, so one background drive task at a time."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._running = asyncio.Event()  # set == currently playing (not paused)
        self._elapsed_at_pause: float = 0.0
        self._t_zero: Optional[float] = None
        self._video_id: Optional[str] = None
        self._buckets: Optional[List[Dict]] = None
        self._duration: float = 0.0
        self._last_params: Dict[str, int] = {}
        self._current_fx_idx: Optional[int] = None
        self._peaks: List[Dict] = []  # sorted by midpoint ascending
        self._next_peak_idx: int = 0
        self._ws: Optional[Any] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._ws_ready = asyncio.Event()
        self._manual_override = False  # True while a manually-picked effect/params is active
        self._club_sync_enabled = True  # persistent — master on/off for heatmap-driven updates
        self._peak_fx_enabled = True    # persistent — whether effect/palette/color change at peaks

    @property
    def enabled(self) -> bool:
        return bool(settings.wled_ip)

    def _elapsed(self) -> float:
        if self._t_zero is None:
            return self._elapsed_at_pause
        return time.monotonic() - self._t_zero

    async def start(
        self,
        video_id: str,
        heatmap: List[Dict],
        start_at: float = 0.0,
        peaks: Optional[List[Dict]] = None,
    ) -> None:
        """Stop whatever was running and start driving WLED for *video_id*."""
        await self.stop()
        if not self.enabled or not heatmap:
            return

        self._manual_override = False
        self._last_params = {}

        # 2. Process the heatmap (and its peaks — already computed by the
        #    caller for the DJ-mode seek target, reused here as-is).
        buckets = sorted(heatmap, key=lambda b: b["start_time"])
        self._video_id = video_id
        self._buckets = buckets
        self._duration = buckets[-1]["end_time"]
        self._elapsed_at_pause = max(0.0, start_at)
        self._t_zero = time.monotonic() - self._elapsed_at_pause

        self._peaks = sorted(peaks or [], key=lambda p: p["midpoint"])
        self._next_peak_idx = 0
        while (
            self._next_peak_idx < len(self._peaks)
            and self._peaks[self._next_peak_idx]["midpoint"] < self._elapsed_at_pause
        ):
            self._next_peak_idx += 1

        # 1. Change effect (+ palette + color) first — a fresh look for this
        #    song, pushed immediately rather than waiting for the first peak
        #    to roll around (which could leave the previous song's look
        #    running for a while).
        if self._club_sync_enabled:
            if self._peak_fx_enabled:
                seg = self._pick_new_look()
                if seg:
                    await self._send_seg(seg, ready_timeout=6.0)
            elif self._current_fx_idx is None:
                # Peak FX is off, but we still need *some* effect reference
                # to know which sliders to pulse — bootstrap once.
                pool = catalog.audio_reactive_indices()
                if pool:
                    self._current_fx_idx = random.choice(pool)
                    await self._send_seg({"fx": self._current_fx_idx}, ready_timeout=6.0)

        # 3. Then sync — the background loop drives sx/ix/c1-3 for the
        #    effect just set, and (if Peak FX is on) rotates it further at
        #    each upcoming peak.
        self._running.set()
        self._task = asyncio.create_task(self._run())
        logger.info(
            "WLED: club sync driving video_id=%s from t=%.1fs (fx=%s, %d peaks ahead)",
            video_id, start_at, self._current_fx_idx, len(self._peaks) - self._next_peak_idx,
        )

    async def pause(self) -> None:
        if self._t_zero is not None:
            self._elapsed_at_pause = self._elapsed()
            self._t_zero = None
        self._running.clear()
        logger.debug("WLED: paused at t=%.1fs", self._elapsed_at_pause)

    async def resume(self) -> None:
        if not self._task:
            return
        self._t_zero = time.monotonic() - self._elapsed_at_pause
        self._running.set()
        logger.debug("WLED: resumed at t=%.1fs", self._elapsed_at_pause)

    async def seek(self, seconds: float) -> None:
        if not self._task:
            return
        self._elapsed_at_pause = max(0.0, seconds)
        if self._t_zero is not None:
            self._t_zero = time.monotonic() - self._elapsed_at_pause
        # Re-sync which peak is "next" so seeking forward doesn't fire every
        # peak skipped over, and seeking backward doesn't miss the one just landed on.
        self._next_peak_idx = 0
        while (
            self._next_peak_idx < len(self._peaks)
            and self._peaks[self._next_peak_idx]["midpoint"] < self._elapsed_at_pause
        ):
            self._next_peak_idx += 1

    async def set_palette(self, palette_name: str) -> bool:
        """
        Apply just a palette, leaving whatever effect/speed is currently
        running untouched. Standalone action — the heatmap auto-sync loop
        never touches `pal`, so this doesn't need to suspend it.
        """
        if not self.enabled:
            return False
        pal_idx = catalog.palette_index(palette_name)
        if pal_idx is None:
            return False

        sent = await self._send_seg({"pal": pal_idx}, ready_timeout=6.0)
        if not sent:
            logger.warning("WLED: palette=%s not delivered (websocket unavailable)", palette_name)
            return False

        logger.info("WLED: palette=%s applied (pal=%s)", palette_name, pal_idx)
        return True

    async def set_effect(self, effect_name: str) -> bool:
        """
        Apply just an effect, leaving speed/intensity/palette untouched.
        Unlike palette, the heatmap loop *does* drive `fx` — so this sets
        a manual override, otherwise the next tick (or player heartbeat)
        would overwrite the pick within ~1s.
        """
        if not self.enabled:
            return False
        fx_idx = catalog.effect_index(effect_name)
        if fx_idx is None:
            return False

        sent = await self._send_seg({"fx": fx_idx}, ready_timeout=6.0)
        if not sent:
            logger.warning("WLED: effect=%s not delivered (websocket unavailable)", effect_name)
            return False

        self._manual_override = True
        self._current_fx_idx = fx_idx
        self._last_params = {}
        logger.info("WLED: effect=%s applied (fx=%s)", effect_name, fx_idx)
        return True

    async def set_params(self, params: Dict[str, int]) -> bool:
        """
        Live-tweak the current effect's sliders (sx/ix/c1/c2/c3) — a partial
        update, only the given keys are sent. Same manual-override rules as
        `set_effect()` since these are heatmap-driven.
        """
        if not self.enabled:
            return False
        seg = {k: max(0, min(255, int(v))) for k, v in params.items() if k in _PARAM_KEYS}
        if not seg:
            return False

        sent = await self._send_seg(seg, ready_timeout=6.0)
        if not sent:
            logger.warning("WLED: params=%s not delivered (websocket unavailable)", seg)
            return False

        self._manual_override = True
        self._last_params.update(seg)
        logger.info("WLED: params applied %s", seg)
        return True

    async def set_power(self, on: bool) -> bool:
        """Turn the strip on/off. Top-level `on` field, not a `seg` value — leaves everything else untouched."""
        if not self.enabled:
            return False
        sent = await self._send_payload({"on": on}, ready_timeout=6.0)
        if not sent:
            logger.warning("WLED: power=%s not delivered (websocket unavailable)", on)
            return False
        logger.info("WLED: power=%s applied", on)
        return True

    async def set_brightness(self, bri: int) -> bool:
        """Set overall strip brightness (0-255). Top-level `bri` field, independent of everything else."""
        if not self.enabled:
            return False
        sent = await self._send_payload({"bri": max(0, min(255, int(bri)))}, ready_timeout=6.0)
        if not sent:
            logger.warning("WLED: brightness=%s not delivered (websocket unavailable)", bri)
            return False
        logger.info("WLED: brightness=%s applied", bri)
        return True

    async def set_color(self, r: int, g: int, b: int, slot: int = 0) -> bool:
        """
        Set one of the segment's 3 color slots (0=primary, 1=secondary,
        2=tertiary) — the same "Color 1/2/3" slots WLED's own color wheel
        writes to (`selectSlot()` + `setColor()` in its UI). Several
        "structural" palettes (Colors 1&2, Color Gradient, Colors Only, ...)
        render *from* these slots instead of a fixed gradient, so they only
        look right once slot 2/3 actually have a color set — they default
        to black. Independent of the club-sync loop — it never touches
        `col`, so no manual override needed.
        """
        if not self.enabled or slot not in (0, 1, 2):
            return False
        rgb = [max(0, min(255, int(v))) for v in (r, g, b)]
        # Match the exact wire format WLED's own UI sends
        # ({"seg":{"col":[[],[],[]]}} with only the target slot filled in
        # as [r,g,b,w]) — the other two slots stay empty, meaning "leave
        # unchanged", not "clear to black".
        col: List[Any] = [[], [], []]
        col[slot] = rgb + [0]
        sent = await self._send_seg({"col": col}, ready_timeout=6.0)
        if not sent:
            logger.warning("WLED: color=%s slot=%s not delivered (websocket unavailable)", rgb, slot)
            return False
        logger.info("WLED: color=%s slot=%s applied", rgb, slot)
        return True

    async def resume_auto_sync(self) -> None:
        """Drop the manual override and resume heatmap-driven club sync, if a song is active."""
        if not self._manual_override:
            return
        self._manual_override = False
        if self._task is not None:
            self._t_zero = time.monotonic() - self._elapsed_at_pause
            self._running.set()
            logger.debug("WLED: manual override cleared, auto-sync resumed at t=%.1fs", self._elapsed_at_pause)

    async def set_club_sync(self, enabled: bool) -> bool:
        """
        Persistent on/off for the whole heatmap-driven club-light loop —
        unlike the manual override (which auto-clears on the next song),
        this stays off across songs until explicitly turned back on.
        """
        self._club_sync_enabled = enabled
        if enabled and self._task is not None:
            self._manual_override = False
            self._t_zero = time.monotonic() - self._elapsed_at_pause
            self._running.set()
            logger.debug("WLED: club sync re-enabled, resumed at t=%.1fs", self._elapsed_at_pause)
        else:
            logger.info("WLED: club sync %s", "enabled" if enabled else "disabled")
        return True

    async def set_peak_fx(self, enabled: bool) -> bool:
        """
        Persistent on/off for changing effect/palette/color at song start
        and at each detected heatmap peak. When off, whatever effect is
        currently set just keeps getting its sliders pulsed by Club Sync,
        without ever being swapped out.
        """
        self._peak_fx_enabled = enabled
        logger.info("WLED: peak fx %s", "enabled" if enabled else "disabled")
        return True

    def _pick_new_look(self) -> Dict[str, Any]:
        """
        A fresh "light cue": new random audio-reactive effect (never the one
        already showing), new random palette, new random vivid color on the
        primary slot — like a club rig's look changing on cue.
        """
        seg: Dict[str, Any] = {}

        pool = catalog.audio_reactive_indices()
        if pool:
            choices = [f for f in pool if f != self._current_fx_idx] or pool
            self._current_fx_idx = random.choice(choices)
            seg["fx"] = self._current_fx_idx
        # A new effect's sliders mean something different now — force a
        # resend of whichever are active instead of comparing against the
        # previous effect's last-sent values.
        self._last_params = {}

        if catalog.PALETTES:
            seg["pal"] = random.randrange(len(catalog.PALETTES))

        # Full saturation/value, random hue — always a vivid, visible color
        # (plain random RGB can land on muddy near-black).
        r, g, b = (round(c * 255) for c in colorsys.hsv_to_rgb(random.random(), 1.0, 1.0))
        seg["col"] = [[r, g, b, 0], [], []]

        return seg

    async def sync_time(self, video_id: str, current_time: float, state: int) -> None:
        """
        Resync the drive clock to the player's own heartbeat (`ping` with
        currentTime). This is the ground truth for playback position — it
        corrects drift from buffering, native player controls, or network
        jitter that our own free-running clock and the `control` messages
        can't see.

        state follows the YouTube IFrame API: -1 unstarted, 0 ended,
        1 playing, 2 paused, 3 buffering, 5 cued.
        """
        if not self._task or video_id != self._video_id:
            return

        if state == 0:
            await self.stop()
            return

        self._elapsed_at_pause = max(0.0, current_time)
        if state == 1:
            self._t_zero = time.monotonic() - self._elapsed_at_pause
            self._running.set()
        elif state in (2, 3):
            self._t_zero = None
            self._running.clear()

        # The player just told us exactly where it is — reflect that now
        # instead of waiting for the background loop's next tick.
        await self._maybe_send(self._elapsed_at_pause)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("WLED: drive task raised on stop")
            self._task = None
        self._video_id = None
        self._buckets = None
        self._duration = 0.0
        self._last_params = {}
        # _current_fx_idx is intentionally left as-is (sticky) — if Peak FX
        # is off, the next song should keep pulsing whatever effect was
        # already showing rather than losing track of it.
        self._peaks = []
        self._next_peak_idx = 0
        self._manual_override = False
        self._t_zero = None
        self._elapsed_at_pause = 0.0
        self._running.clear()

    async def aclose(self) -> None:
        """Release the websocket connection. Call once at app shutdown."""
        await self.stop()
        if self._ws_task is not None:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None
        self._ws = None
        self._ws_ready.clear()

    def _ensure_ws_task(self) -> None:
        """Start the connection-maintaining task once, lazily, on first use."""
        if self._ws_task is None or self._ws_task.done():
            self._ws_task = asyncio.create_task(self._ws_run())

    async def _ws_run(self) -> None:
        """
        Keep one WebSocket connection to WLED open for as long as the app
        runs. `websockets.connect` used as an async iterator reconnects with
        backoff on its own whenever the connection drops, so this loop just
        needs to track readiness and drain incoming messages (state
        confirmations WLED pushes back — nothing we currently act on).
        """
        uri = f"ws://{settings.wled_ip}/ws"
        async for ws in websockets.connect(uri, open_timeout=5):
            self._ws = ws
            self._ws_ready.set()
            logger.info("WLED: websocket connected (%s)", uri)
            try:
                async for _ in ws:
                    pass
            except websockets.ConnectionClosed:
                logger.debug("WLED: websocket closed, reconnecting")
            finally:
                self._ws_ready.clear()
                self._ws = None

    async def _send_payload(self, payload: Dict[str, Any], ready_timeout: float = 2.0) -> bool:
        """Send a top-level state update over the websocket. Returns whether it actually went out."""
        self._ensure_ws_task()
        try:
            await asyncio.wait_for(self._ws_ready.wait(), timeout=ready_timeout)
        except asyncio.TimeoutError:
            logger.debug("WLED: websocket not ready, dropping update")
            return False

        raw = json.dumps(payload)
        print(f"DEBUG: WLED WS send {raw}")
        try:
            await self._ws.send(raw)
            return True
        except Exception as exc:
            print(f"DEBUG: WLED send failed for {payload}: {type(exc).__name__}: {exc}")
            logger.debug("WLED: send failed: %s: %s", type(exc).__name__, exc)
            return False

    async def _send_seg(self, seg: Dict[str, Any], ready_timeout: float = 2.0) -> bool:
        """Send a `seg` (segment) update — sx/ix/fx/pal/col/c1-c3 all live here."""
        return await self._send_payload({"seg": seg}, ready_timeout)

    async def _maybe_send(self, t: float) -> None:
        """
        Club-sync tick: if Peak FX is on, change the look on crossing into a
        new detected peak; either way, drive whichever sliders the current
        effect exposes from the heatmap value, for time *t*.
        """
        if not self._club_sync_enabled or self._manual_override or not self._buckets or t > self._duration:
            return

        v = _value_at(self._buckets, t)
        seg: Dict[str, Any] = {}

        if self._peak_fx_enabled:
            crossed = False
            while self._next_peak_idx < len(self._peaks) and t >= self._peaks[self._next_peak_idx]["midpoint"]:
                self._next_peak_idx += 1
                crossed = True
            if crossed:
                seg.update(self._pick_new_look())

        if self._current_fx_idx is None:
            # No look chosen yet (Peak FX has been off since this controller
            # was created) — bootstrap once so there's something to pulse.
            pool = catalog.audio_reactive_indices()
            if pool:
                self._current_fx_idx = random.choice(pool)
                seg["fx"] = self._current_fx_idx

        if self._current_fx_idx is not None:
            controls = catalog.effect_controls(self._current_fx_idx)["labels"]
            val = _to_sx(v, settings.wled_sx_min, settings.wled_sx_max, settings.wled_gamma)
            for key in _PARAM_KEYS:
                if not controls.get(key):
                    continue
                last = self._last_params.get(key)
                if last is None or abs(val - last) >= settings.wled_deadband:
                    seg[key] = val
                    self._last_params[key] = val

        if seg:
            await self._send_seg(seg)

    async def _run(self) -> None:
        """
        Fallback ticker: keeps the effect moving between player heartbeats
        using our own extrapolated clock. `sync_time()` is the primary
        driver and corrects this clock (and sends directly) on every
        heartbeat, so this loop mostly fills the gaps.
        """
        try:
            while True:
                await self._running.wait()
                t = self._elapsed()
                if t > self._duration:
                    break
                await self._maybe_send(t)
                await asyncio.sleep(settings.wled_rate)
        finally:
            logger.debug("WLED: drive loop ended for video_id=%s", self._video_id)


# Single shared instance – import this everywhere
wled_controller = WledSyncController()
