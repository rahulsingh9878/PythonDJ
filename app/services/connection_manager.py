from typing import List
from fastapi import WebSocket
import json
from ..utils.helpers import generate_qr_base64

class DJConnectionManager:
    def __init__(self):
        # All connected clients
        self.all_connections: List[WebSocket] = []
        # Clients identified as "player" (the main DJ screen)
        self.player_connections: List[WebSocket] = []
        # Clients identified as "controller" (phone remotes)
        self.controller_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket, role: str = "controller"):
        await websocket.accept()
        self.all_connections.append(websocket)
        if role == "player":
            self.player_connections.append(websocket)
        else:
            self.controller_connections.append(websocket)
        print(f"New {role} connected. Total: {len(self.all_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.all_connections:
            self.all_connections.remove(websocket)
        if websocket in self.player_connections:
            self.player_connections.remove(websocket)
        if websocket in self.controller_connections:
            self.controller_connections.remove(websocket)

    async def broadcast(self, message: dict, sender: WebSocket = None, target_role: str = None):
        """
        Broadcasts a message.
        target_role: "player", "controller", or None (all)
        """
        targets = self.all_connections
        if target_role == "player":
            targets = self.player_connections
        elif target_role == "controller":
            targets = self.controller_connections

        for connection in list(targets):
            if connection == sender:
                continue
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

manager = DJConnectionManager()
