import asyncio
import json
import logging

from fastapi import WebSocket
from trademachine.core.logger import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.queue: asyncio.Queue = asyncio.Queue()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: str):
        dead = []
        for ws in self.active_connections:
            try:
                await ws.send_text(message)
            except Exception as e:
                logger.warning(f"Broadcast failed for client, dropping: {e}")
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def run_broadcaster(self):
        """Consume events from queue and broadcast to all WebSocket clients."""
        while True:
            try:
                event = await self.queue.get()
                await self.broadcast(json.dumps(event))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Broadcaster error: {e}")


manager = ConnectionManager()
