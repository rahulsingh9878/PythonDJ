"""
WebSocket connection management.

DJConnectionManager maintains three connection pools:
  - all_connections  – every connected client
  - player_connections    – the main DJ display / speaker device
  - controller_connections – phone / browser remotes

PlayerBroadcaster and WebAppBroadcaster are thin, typed wrappers that
make the intent at each call-site explicit instead of relying on the
`target_role` string argument.
"""

import logging
from typing import List

from fastapi import WebSocket

from ..utils.helpers import generate_qr_base64  # noqa: F401 – re-exported for convenience

logger = logging.getLogger(__name__)


class DJConnectionManager:
    def __init__(self) -> None:
        self.all_connections: List[WebSocket] = []
        self.player_connections: List[WebSocket] = []
        self.controller_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket, role: str = "controller") -> None:
        await websocket.accept()
        self.all_connections.append(websocket)
        if role == "player":
            self.player_connections.append(websocket)
        else:
            self.controller_connections.append(websocket)
        logger.info(
            "Client connected role=%s total=%d", role, len(self.all_connections)
        )

    def disconnect(self, websocket: WebSocket) -> None:
        for pool in (
            self.all_connections,
            self.player_connections,
            self.controller_connections,
        ):
            if websocket in pool:
                pool.remove(websocket)
        logger.info("Client disconnected. Remaining=%d", len(self.all_connections))

    async def broadcast(
        self,
        message: dict,
        sender: WebSocket = None,
        target_role: str = None,
    ) -> None:
        """
        Send *message* to every client in the target pool.

        Args:
            message:     JSON-serialisable dict.
            sender:      The originating socket; excluded from the broadcast.
            target_role: ``"player"``, ``"controller"``, or ``None`` (all).
        """
        if target_role == "player":
            targets = self.player_connections
        elif target_role == "controller":
            targets = self.controller_connections
        else:
            targets = self.all_connections

        dead: List[WebSocket] = []
        for connection in list(targets):
            if connection is sender:
                continue
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)

        # Clean up broken sockets discovered during broadcast
        for ws in dead:
            self.disconnect(ws)


class PlayerBroadcaster:
    """Sends messages exclusively to the Player (display / speaker) role."""

    def __init__(self, manager: DJConnectionManager) -> None:
        self.manager = manager

    async def send(
        self, msg_type: str, data: dict, sender: WebSocket = None
    ) -> None:
        await self.manager.broadcast(
            {"type": msg_type, "data": data},
            sender=sender,
            target_role="player",
        )


class WebAppBroadcaster:
    """Sends messages exclusively to Controller (remote) clients."""

    def __init__(self, manager: DJConnectionManager) -> None:
        self.manager = manager

    async def send(
        self, msg_type: str, data: dict, sender: WebSocket = None
    ) -> None:
        await self.manager.broadcast(
            {"type": msg_type, "data": data},
            sender=sender,
            target_role="controller",
        )


# ---------------------------------------------------------------------------
# Module-level singletons – import these in other modules
# ---------------------------------------------------------------------------
manager = DJConnectionManager()
player_broadcaster = PlayerBroadcaster(manager)
webapp_broadcaster = WebAppBroadcaster(manager)
