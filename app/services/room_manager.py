"""
Room management service.

A Room is an isolated DJ session with its own host, members, and lifecycle.
RoomManager is the single source of truth for all active rooms.

Room lifecycle:
  - Created by a host via create_room(); destroyed when the host disconnects.
  - Members join via join_room() and leave via leave_room() or on disconnect.
  - When the host disconnects, all remaining members receive room_closed.

Room IDs are 6-character uppercase alphanumeric codes (e.g. "XK7A2Q"),
designed to be shared verbally or via QR code.
"""

import logging
import random
import string
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)

_ID_CHARS = string.ascii_uppercase + string.digits


def _generate_room_id() -> str:
    return "".join(random.choices(_ID_CHARS, k=6))


@dataclass
class Room:
    id: str
    name: str
    host: WebSocket
    members: List[WebSocket] = field(default_factory=list)
    max_members: int = 20
    created_at: float = field(default_factory=time.time)
    # Media-plane pools — /ws/sync connections scoped to this room
    sync_controllers: List[WebSocket] = field(default_factory=list)
    sync_players: List[WebSocket] = field(default_factory=list)
    # Per-room vol/mute state (independent across rooms)
    player_state: Dict[str, Any] = field(default_factory=lambda: {
        "maxVol": 100,
        "isMuted": False,
    })

    def member_count(self) -> int:
        # host + members
        return 1 + len(self.members)

    def is_full(self) -> bool:
        return self.member_count() >= self.max_members

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "member_count": self.member_count(),
            "max_members": self.max_members,
            "created_at": self.created_at,
        }


class RoomManager:
    def __init__(self) -> None:
        self._rooms: Dict[str, Room] = {}
        # Presence reverse index (/ws/room connections)
        self._ws_to_room: Dict[int, str] = {}  # keyed by id(ws)
        # Media reverse index (/ws/sync connections)
        self._sync_ws_to_room: Dict[int, str] = {}  # keyed by id(ws)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_room(
        self,
        host: WebSocket,
        name: str,
        max_members: int = 20,
    ) -> Room:
        if id(host) in self._ws_to_room:
            existing_id = self._ws_to_room[id(host)]
            raise ValueError(f"ALREADY_IN_ROOM:{existing_id}")

        room_id = self._unique_id()
        room = Room(id=room_id, name=name, host=host, max_members=max_members)
        self._rooms[room_id] = room
        self._ws_to_room[id(host)] = room_id
        logger.info("Room created id=%s name=%r", room_id, name)
        return room

    def join_room(self, room_id: str, ws: WebSocket) -> Room:
        room = self._rooms.get(room_id)
        if room is None:
            raise ValueError("ROOM_NOT_FOUND")
        if id(ws) in self._ws_to_room:
            existing_id = self._ws_to_room[id(ws)]
            raise ValueError(f"ALREADY_IN_ROOM:{existing_id}")
        if room.is_full():
            raise ValueError("ROOM_FULL")

        room.members.append(ws)
        self._ws_to_room[id(ws)] = room_id
        logger.info("Room joined id=%s members=%d", room_id, room.member_count())
        return room

    def leave_room(self, ws: WebSocket) -> tuple[Optional[str], bool]:
        """
        Remove *ws* from whatever room it is in.

        Returns (room_id, was_destroyed).
        was_destroyed is True when ws was the host and the room is closed.
        Returns (None, False) if the socket was not in any room.
        """
        room_id = self._ws_to_room.pop(id(ws), None)
        if room_id is None:
            return None, False

        room = self._rooms.get(room_id)
        if room is None:
            return room_id, False

        if ws is room.host:
            # Host left — destroy the room entirely.
            self._destroy_room(room)
            return room_id, True

        if ws in room.members:
            room.members.remove(ws)
        logger.info("Room left id=%s remaining=%d", room_id, room.member_count())
        return room_id, False

    def get_room(self, room_id: str) -> Optional[Room]:
        return self._rooms.get(room_id)

    def room_of(self, ws: WebSocket) -> Optional[Room]:
        room_id = self._ws_to_room.get(id(ws))
        return self._rooms.get(room_id) if room_id else None

    def list_rooms(self) -> List[dict]:
        return [r.to_dict() for r in self._rooms.values()]

    async def broadcast_to_room(
        self,
        room: Room,
        message: dict,
        exclude: Optional[WebSocket] = None,
    ) -> None:
        targets = [room.host] + room.members
        dead: List[WebSocket] = []
        for ws in targets:
            if ws is exclude:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.leave_room(ws)

    # ------------------------------------------------------------------
    # Sync (media-plane) API
    # ------------------------------------------------------------------

    def register_sync(self, room_id: str, ws: WebSocket, role: str) -> Room:
        """Register a /ws/sync connection into the room's media pool."""
        room = self._rooms.get(room_id)
        if room is None:
            raise ValueError("ROOM_NOT_FOUND")
        if role == "player":
            room.sync_players.append(ws)
        else:
            room.sync_controllers.append(ws)
        self._sync_ws_to_room[id(ws)] = room_id
        logger.info("Sync registered role=%s room=%s", role, room_id)
        return room

    def unregister_sync(self, ws: WebSocket) -> Optional[str]:
        """Remove a /ws/sync connection from its room's media pool. O(1) lookup."""
        room_id = self._sync_ws_to_room.pop(id(ws), None)
        if room_id is None:
            return None
        room = self._rooms.get(room_id)
        if room:
            if ws in room.sync_controllers:
                room.sync_controllers.remove(ws)
            if ws in room.sync_players:
                room.sync_players.remove(ws)
        return room_id

    async def broadcast_sync(
        self,
        room_id: str,
        message: dict,
        role: Optional[str] = None,
        exclude: Optional[WebSocket] = None,
    ) -> None:
        """Broadcast to media-plane connections in a room, optionally filtered by role."""
        room = self._rooms.get(room_id)
        if room is None:
            return
        if role == "controller":
            targets = list(room.sync_controllers)
        elif role == "player":
            targets = list(room.sync_players)
        else:
            targets = list(room.sync_controllers) + list(room.sync_players)

        dead: List[WebSocket] = []
        for ws in targets:
            if ws is exclude:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.unregister_sync(ws)

    async def notify_sync_closed(self, room: Room) -> None:
        """Push room_closed to all media-plane connections before the room is destroyed."""
        msg = {"type": "room_closed", "data": {"room_id": room.id, "reason": "host_left"}}
        for ws in list(room.sync_controllers) + list(room.sync_players):
            try:
                await ws.send_json(msg)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _unique_id(self) -> str:
        for _ in range(10):
            candidate = _generate_room_id()
            if candidate not in self._rooms:
                return candidate
        raise RuntimeError("Could not generate a unique room ID")

    def _destroy_room(self, room: Room) -> None:
        self._rooms.pop(room.id, None)
        for ws in room.members:
            self._ws_to_room.pop(id(ws), None)
        for ws in list(room.sync_controllers) + list(room.sync_players):
            self._sync_ws_to_room.pop(id(ws), None)
        logger.info("Room destroyed id=%s", room.id)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
room_manager = RoomManager()
