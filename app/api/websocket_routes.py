"""
WebSocket routes.

Primary route:  /ws/sync?role=controller|player
  - Unified hub for all real-time DJ operations.
  - Message envelope: {"type": "<action>", "data": {...}}

Room route:  /ws/room
  - Create, join, leave, and list DJ session rooms.
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
from ..services.room_manager import room_manager
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
    room_id: str = Query(None),
):
    """
    Unified WebSocket hub for all DJ operations.

    Accepted roles:
      - ``controller`` – phone / browser remote (sends commands, receives UI updates)
      - ``player``     – display / speaker device (receives play commands)

    room_id (optional):
      When provided the connection is registered in that room's media pool and
      all broadcasts are scoped to that room only.  Without room_id the
      connection falls back to the global pool (backward compatible).

    Message format::

        {"type": "play|vol|mute|control|qr|ping|suggest|radio|search", "data": {...}}
    """
    # ----------------------------------------------------------------
    # Connect – room-scoped or global
    # ----------------------------------------------------------------
    room = None
    if room_id:
        await websocket.accept()
        try:
            room = room_manager.register_sync(room_id, websocket, role)
        except ValueError:
            await websocket.close(code=4001, reason="Room not found")
            return
        # Push this room's own vol/mute state
        await websocket.send_json(
            {"type": "vol", "data": {"volume": room.player_state.get("maxVol", 100)}}
        )
        await websocket.send_json(
            {"type": "mute", "data": {"isMuted": room.player_state.get("isMuted", False)}}
        )
    else:
        await manager.connect(websocket, role)
        await websocket.send_json(
            {"type": "vol", "data": {"volume": app_state.player_context.get("maxVol", 100)}}
        )
        await websocket.send_json(
            {"type": "mute", "data": {"isMuted": app_state.player_context.get("isMuted", False)}}
        )

    # ----------------------------------------------------------------
    # Broadcast helpers – pick room-scoped or global path once
    # ----------------------------------------------------------------
    async def _broadcast(message: dict, target_role: str = None) -> None:
        if room_id:
            await room_manager.broadcast_sync(room_id, message, role=target_role, exclude=websocket)
        else:
            await manager.broadcast(message, sender=websocket, target_role=target_role)

    async def _broadcast_controllers(msg_type: str, data: dict) -> None:
        msg = {"type": msg_type, "data": data}
        if room_id:
            await room_manager.broadcast_sync(room_id, msg, role="controller")
        else:
            await webapp_broadcaster.send(msg_type, data)

    try:
        while True:
            raw = await websocket.receive_json()
            msg_type: str = raw.get("type", "")
            msg_data: dict = raw.get("data") or {}

            logger.debug("WS sync type=%s role=%s room=%s", msg_type, role, room_id)

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
                    await _broadcast({"type": "player_status", "data": payload}, target_role="controller")
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
                    # Forward the play command to all players in the room
                    await _broadcast({"type": "play", "data": msg_data}, target_role="player")
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

                await _broadcast_controllers("search_result", context)

            # ----------------------------------------------------------------
            # vol / mute – volume sync
            # ----------------------------------------------------------------
            elif msg_type == "vol":
                if "volume" in msg_data:
                    if room:
                        room.player_state["maxVol"] = msg_data["volume"]
                    else:
                        app_state.player_context["maxVol"] = msg_data["volume"]
                await _broadcast({"type": "vol", "data": msg_data})

            elif msg_type == "mute":
                if "isMuted" in msg_data:
                    if room:
                        room.player_state["isMuted"] = bool(msg_data["isMuted"])
                    else:
                        app_state.player_context["isMuted"] = bool(msg_data["isMuted"])
                await _broadcast({"type": "mute", "data": msg_data})

            # ----------------------------------------------------------------
            # control – play / pause / next / prev
            # ----------------------------------------------------------------
            elif msg_type == "control":
                logger.debug("Control action=%s", msg_data.get("action"))
                await _broadcast({"type": "control", "data": msg_data})

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
                    await _broadcast_controllers("radio_result", result)

            # ----------------------------------------------------------------
            # search – search + broadcast to controllers
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
                await _broadcast_controllers("search_result", result)

            else:
                logger.warning("Unknown WS message type=%s", msg_type)

    except WebSocketDisconnect:
        logger.info("WS client disconnected role=%s room=%s", role, room_id)
    except Exception as exc:
        logger.exception("WS sync error role=%s room=%s: %s", role, room_id, exc)
    finally:
        if room_id:
            room_manager.unregister_sync(websocket)
        else:
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
# Room route – create / join / leave / list rooms
# ---------------------------------------------------------------------------

@router.websocket("/ws/room")
async def websocket_room_hub(websocket: WebSocket):
    """
    WebSocket hub for DJ session room management.

    On connect the server immediately pushes the current rooms list so the
    client is in sync without having to send a list_rooms message first.

    Client → Server message types:

        create_room  {"name": "...", "max_members": 20}
        join_room    {"room_id": "XK7A2Q"}
        leave_room   {}
        list_rooms   {}
        ping         {}

    Server → Client (targeted):

        rooms_list   {"rooms": [...]}
        room_created {"room_id", "name", "member_count", "role": "host"}
        room_joined  {"room_id", "name", "member_count", "role": "member"}
        error        {"code": "ROOM_NOT_FOUND|ROOM_FULL|ALREADY_IN_ROOM|NAME_REQUIRED", "message": "..."}
        pong         {"ts": ...}

    Server → Room (broadcast):

        member_joined {"member_count": N}
        member_left   {"member_count": N}
        room_closed   {"room_id": "...", "reason": "host_left"}
    """
    await websocket.accept()
    try:
        # Push current room list immediately on connect.
        await websocket.send_json(
            {"type": "rooms_list", "data": {"rooms": room_manager.list_rooms()}}
        )

        while True:
            raw = await websocket.receive_json()
            msg_type: str = raw.get("type", "")
            msg_data: dict = raw.get("data") or {}

            logger.debug("WS room type=%s", msg_type)

            # ----------------------------------------------------------------
            # ping / pong – heartbeat
            # ----------------------------------------------------------------
            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "ts": time.time()})

            # ----------------------------------------------------------------
            # create_room – register a new room, caller becomes host
            # ----------------------------------------------------------------
            elif msg_type == "create_room":
                name = (msg_data.get("name") or "").strip()
                if not name:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"code": "NAME_REQUIRED", "message": "Room name is required."},
                    })
                    continue

                max_members = int(msg_data.get("max_members", 20))
                try:
                    room = room_manager.create_room(
                        host=websocket,
                        name=name,
                        max_members=max_members,
                    )
                except ValueError as exc:
                    code = str(exc).split(":")[0]
                    await websocket.send_json({
                        "type": "error",
                        "data": {"code": code, "message": str(exc)},
                    })
                    continue

                await websocket.send_json({
                    "type": "room_created",
                    "data": {**room.to_dict(), "role": "host"},
                })
                logger.info("Room created id=%s name=%r", room.id, room.name)

            # ----------------------------------------------------------------
            # join_room – add caller to an existing room as a member
            # ----------------------------------------------------------------
            elif msg_type == "join_room":
                room_id = (msg_data.get("room_id") or "").strip().upper()
                if not room_id:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"code": "NAME_REQUIRED", "message": "room_id is required."},
                    })
                    continue

                try:
                    room = room_manager.join_room(room_id=room_id, ws=websocket)
                except ValueError as exc:
                    code = str(exc).split(":")[0]
                    await websocket.send_json({
                        "type": "error",
                        "data": {"code": code, "message": str(exc)},
                    })
                    continue

                # Notify the joining member.
                await websocket.send_json({
                    "type": "room_joined",
                    "data": {**room.to_dict(), "role": "member"},
                })
                # Notify everyone else already in the room.
                await room_manager.broadcast_to_room(
                    room,
                    {"type": "member_joined", "data": {"member_count": room.member_count()}},
                    exclude=websocket,
                )
                logger.info("Room joined id=%s members=%d", room_id, room.member_count())

            # ----------------------------------------------------------------
            # leave_room – explicit departure (mirrors disconnect cleanup)
            # ----------------------------------------------------------------
            elif msg_type == "leave_room":
                # Snapshot BEFORE leave_room() destroys the room.
                current_room = room_manager.room_of(websocket)
                members_snapshot = list(current_room.members) if current_room else []

                if current_room and websocket is current_room.host:
                    await room_manager.notify_sync_closed(current_room)

                room_id, was_destroyed = room_manager.leave_room(websocket)
                if room_id is None:
                    continue

                if was_destroyed:
                    closed_msg = {
                        "type": "room_closed",
                        "data": {"room_id": room_id, "reason": "host_left"},
                    }
                    for ws in members_snapshot:
                        try:
                            await ws.send_json(closed_msg)
                        except Exception:
                            pass
                    logger.info("Room closed by host leave id=%s", room_id)
                else:
                    room = room_manager.get_room(room_id)
                    if room:
                        await room_manager.broadcast_to_room(
                            room,
                            {"type": "member_left", "data": {"member_count": room.member_count()}},
                        )

            # ----------------------------------------------------------------
            # list_rooms – return current snapshot
            # ----------------------------------------------------------------
            elif msg_type == "list_rooms":
                await websocket.send_json({
                    "type": "rooms_list",
                    "data": {"rooms": room_manager.list_rooms()},
                })

            else:
                logger.warning("Unknown WS room message type=%s", msg_type)

    except WebSocketDisconnect:
        logger.info("WS room client disconnected")
    except Exception as exc:
        logger.exception("WS room error: %s", exc)
    finally:
        # Snapshot BEFORE leave_room() destroys the room.
        current_room = room_manager.room_of(websocket)
        members_snapshot = list(current_room.members) if current_room else []

        if current_room and websocket is current_room.host:
            await room_manager.notify_sync_closed(current_room)

        room_id, was_destroyed = room_manager.leave_room(websocket)
        if room_id is not None:
            if was_destroyed:
                closed_msg = {
                    "type": "room_closed",
                    "data": {"room_id": room_id, "reason": "host_left"},
                }
                for ws in members_snapshot:
                    try:
                        await ws.send_json(closed_msg)
                    except Exception:
                        pass
                logger.info("Room destroyed on host disconnect id=%s", room_id)
            else:
                room = room_manager.get_room(room_id)
                if room:
                    await room_manager.broadcast_to_room(
                        room,
                        {"type": "member_left", "data": {"member_count": room.member_count()}},
                    )
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
