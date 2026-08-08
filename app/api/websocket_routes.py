"""
WebSocket routes.

Primary route:  /ws/sync?role=controller|player
  - Unified hub for all real-time DJ operations.
  - Message envelope: {"type": "<action>", "data": {...}}

Legacy routes (/ws/, /ws/vol/, /ws/qr/, /ws/player/) are kept for
backward compatibility but log a deprecation warning on first use.

Dedicated routes (/ws/play, /ws/radio) offer direct access to the play
and radio flows without going through the full sync hub.
"""

import logging
import time

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..core.state import app_state
from ..services.connection_manager import manager, webapp_broadcaster
from ..services.music_service import music_service
from ..utils.helpers import generate_qr_base64

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Primary unified hub
# ---------------------------------------------------------------------------

@router.websocket("/ws/sync")
async def websocket_sync_hub(
    websocket: WebSocket,
    role: str = Query("controller"),
):
    """
    Unified WebSocket hub for all DJ operations.

    Accepted roles:
      - ``controller`` – phone / browser remote (sends commands, receives UI updates)
      - ``player``     – display / speaker device (receives play commands)

    Message format::

        {"type": "play|vol|mute|control|qr|ping|suggest|radio|search", "data": {...}}
    """
    await manager.connect(websocket, role)

    # Send initial state so the client is in sync immediately
    await websocket.send_json(
        {"type": "vol", "data": {"volume": app_state.player_context.get("maxVol", 100)}}
    )
    await websocket.send_json(
        {"type": "mute", "data": {"isMuted": app_state.player_context.get("isMuted", False)}}
    )

    try:
        while True:
            raw = await websocket.receive_json()
            msg_type: str = raw.get("type", "")
            msg_data: dict = raw.get("data") or {}

            logger.debug("WS sync type=%s role=%s", msg_type, role)

            # ----------------------------------------------------------------
            # ping / pong – heartbeat + optional player-status relay
            # ----------------------------------------------------------------
            if msg_type == "ping":
                if role == "player" and "currentTime" in msg_data:
                    payload = {
                        "currentTime": msg_data.get("currentTime", 0),
                        "duration": msg_data.get("duration", 0),
                        "videoId": msg_data.get("videoId", ""),
                        "state": msg_data.get("state", -1),
                        "ts": msg_data.get("ts", time.time() * 1000),
                    }
                    logger.debug(
                        "Player heartbeat videoId=%s time=%.2f/%.2f",
                        payload["videoId"],
                        payload["currentTime"],
                        payload["duration"],
                    )
                    await manager.broadcast(
                        {"type": "player_status", "data": payload},
                        target_role="controller",
                    )
                await websocket.send_json({"type": "pong", "ts": time.time()})

            # ----------------------------------------------------------------
            # play – smart play + radio queue
            # ----------------------------------------------------------------
            elif msg_type == "play":
                video_id = msg_data.get("videoId")
                query = msg_data.get("query", "")
                limit = int(msg_data.get("limit", 50))
                max_vol = int(msg_data.get("maxVol", 100))
                music_type = msg_data.get("music_type", "songs")

                if video_id:
                    context = await music_service.play_and_populate(
                        video_id=video_id,
                        title=query or "Unknown",
                        limit=limit,
                        maxVol=max_vol,
                        music_type=music_type,
                        dj_mode=bool(msg_data.get("dj_mode", True)),
                    )
                else:
                    context = await music_service.perform_search(
                        query=query,
                        limit=limit,
                        nextPlay=bool(msg_data.get("nextPlay", True)),
                        maxVol=max_vol,
                        music_type=music_type,
                        videoId=video_id,
                        refresh=bool(msg_data.get("refresh", False)),
                    )

                await webapp_broadcaster.send("search_result", context)

            # ----------------------------------------------------------------
            # vol / mute – volume sync
            # ----------------------------------------------------------------
            elif msg_type == "vol":
                if "volume" in msg_data:
                    app_state.player_context["maxVol"] = msg_data["volume"]
                await manager.broadcast(
                    {"type": "vol", "data": msg_data}, sender=websocket
                )

            elif msg_type == "mute":
                if "isMuted" in msg_data:
                    app_state.player_context["isMuted"] = bool(msg_data["isMuted"])
                await manager.broadcast(
                    {"type": "mute", "data": msg_data}, sender=websocket
                )

            # ----------------------------------------------------------------
            # control – play / pause / next / prev
            # ----------------------------------------------------------------
            elif msg_type == "control":
                logger.debug("Control action=%s", msg_data.get("action"))
                await manager.broadcast(
                    {"type": "control", "data": msg_data}, sender=websocket
                )

            # ----------------------------------------------------------------
            # qr – generate pairing QR
            # ----------------------------------------------------------------
            elif msg_type == "qr":
                url = msg_data.get("url")
                if url:
                    img = generate_qr_base64(url)
                    await websocket.send_json(
                        {"type": "qr", "data": {"img": img, "url": url}}
                    )

            # ----------------------------------------------------------------
            # suggest – search autocomplete
            # ----------------------------------------------------------------
            elif msg_type == "suggest":
                query = msg_data.get("query", "")
                if query:
                    suggestions = music_service.get_suggestions(query)
                    await websocket.send_json(
                        {"type": "suggestions", "data": {"suggestions": suggestions}}
                    )

            # ----------------------------------------------------------------
            # radio – start radio mode
            # ----------------------------------------------------------------
            elif msg_type == "radio":
                video_id = msg_data.get("videoId")
                if video_id:
                    limit = int(msg_data.get("limit", 50))
                    result = await music_service.start_radio(
                        video_id=video_id, limit=limit
                    )
                    await webapp_broadcaster.send("radio_result", result)

            # ----------------------------------------------------------------
            # search – global search + broadcast
            # ----------------------------------------------------------------
            elif msg_type == "search":
                query = msg_data.get("query", "")
                limit = int(msg_data.get("limit", 50))
                music_type = msg_data.get("music_type", "songs")
                is_refresh = bool(msg_data.get("refresh", False))
                logger.info("WS search query='%s' type=%s", query, music_type)
                result = await music_service.perform_search(
                    query=query,
                    limit=limit,
                    music_type=music_type,
                    refresh=is_refresh,
                )
                await webapp_broadcaster.send("search_result", result)

            else:
                logger.warning("Unknown WS message type=%s", msg_type)

    except WebSocketDisconnect:
        logger.info("WS client disconnected role=%s", role)
    except Exception as exc:
        logger.exception("WS sync error role=%s: %s", role, exc)
    finally:
        manager.disconnect(websocket)
        try:
            await websocket.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Dedicated play route
# ---------------------------------------------------------------------------

@router.websocket("/ws/play")
async def websocket_play_route(websocket: WebSocket):
    """
    Dedicated WebSocket for the play/search flow.

    Accepts the same payload as the ``play`` message in /ws/sync.
    Results are broadcast to all controllers via `webapp_broadcaster`.
    """
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            query: str = data.get("query", "")
            if not query:
                continue

            video_id = data.get("videoId")
            if video_id:
                await music_service.play_and_populate(
                    video_id=video_id,
                    title=query,
                    limit=int(data.get("limit", 50)),
                    maxVol=int(data.get("maxVol", 100)),
                    music_type=data.get("music_type", "songs"),
                )
            else:
                await music_service.perform_search(
                    query=query,
                    limit=int(data.get("limit", 50)),
                    nextPlay=bool(data.get("nextPlay", True)),
                    maxVol=int(data.get("maxVol", 100)),
                    music_type=data.get("music_type", "songs"),
                    videoId=video_id,
                    refresh=bool(data.get("refresh", False)),
                )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("WS play route error: %s", exc)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Dedicated radio route
# ---------------------------------------------------------------------------

@router.websocket("/ws/radio")
async def websocket_radio_route(websocket: WebSocket):
    """
    Dedicated WebSocket for radio mode.

    Input:  ``{"videoId": "...", "limit": 50}``
    Output: ``{"type": "radio_result", "data": {...}}``
    """
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            video_id = data.get("videoId")
            if not video_id:
                continue
            limit = int(data.get("limit", 50))
            result = await music_service.start_radio(video_id=video_id, limit=limit)
            await websocket.send_json({"type": "radio_result", "data": result})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("WS radio route error: %s", exc)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Legacy routes – kept for backward compatibility
# ---------------------------------------------------------------------------

@router.websocket("/ws/")
async def _legacy_ws(websocket: WebSocket):
    logger.warning("Deprecated /ws/ endpoint used – migrate to /ws/sync")
    await websocket.accept()
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        pass


@router.websocket("/ws/vol/")
async def _legacy_vol(websocket: WebSocket):
    logger.warning("Deprecated /ws/vol/ endpoint used – migrate to /ws/sync")
    await websocket.accept()
    try:
        while True:
            vol = await websocket.receive_text()
            await manager.broadcast({"type": "vol", "data": {"volume": vol}})
    except Exception:
        pass


@router.websocket("/ws/qr/")
async def _legacy_qr(websocket: WebSocket):
    logger.warning("Deprecated /ws/qr/ endpoint used – migrate to /ws/sync")
    await websocket.accept()
    try:
        while True:
            url = await websocket.receive_text()
            if url:
                await websocket.send_text(generate_qr_base64(url))
    except Exception:
        pass


@router.websocket("/ws/player/")
async def _legacy_player(websocket: WebSocket):
    import json

    logger.warning("Deprecated /ws/player/ endpoint used – migrate to /ws/sync")
    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {"raw": raw}
            await manager.broadcast({"type": "control", "data": payload})
    except Exception:
        pass
