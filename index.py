from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from typing import List, Dict, Set
from collections import deque
from datetime import datetime

app = FastAPI()

# Configuration CORS plus sécurisée
origins = [
    "https://vps-a6456265.vps.ovh.net",  # Production HTTPS
    "http://vps-a6456265.vps.ovh.net",   # Production HTTP
    "wss://vps-a6456265.vps.ovh.net",    # Production WSS
    "ws://vps-a6456265.vps.ovh.net",     # Production WS
    "http://localhost:8001",              # Développement local
    "http://127.0.0.1:8001",             # Développement local
    "http://localhost:8000",              # Backend local
    "http://127.0.0.1:8000"              # Backend local
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Temporairement permettre toutes les origines pour déboguer
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.pseudos: Dict[WebSocket, str] = {}
        self.message_history = deque(maxlen=100)  # Store last 100 messages

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        # Send message history to new client
        if self.message_history:
            try:
                await websocket.send_json({
                    "type": "history",
                    "messages": list(self.message_history)
                })
            except RuntimeError:
                # Connection might be closed already
                await self.disconnect(websocket)
                return

    async def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        old_pseudo = self.pseudos.pop(websocket, None)
        if old_pseudo:
            # Broadcast disconnection only if we had a pseudo
            remaining_connections = self.active_connections - {websocket}
            if remaining_connections:
                for conn in remaining_connections:
                    try:
                        await conn.send_json({
                            "type": "system",
                            "txt": f"{old_pseudo} has left the chat"
                        })
                    except RuntimeError:
                        # Remove any connections that fail
                        await self.disconnect(conn)
            await self.broadcast_pseudos()

    async def receive_pseudo(self, websocket: WebSocket, pseudo: str):
        if websocket not in self.active_connections:
            return
        
        old_pseudo = self.pseudos.get(websocket)
        self.pseudos[websocket] = pseudo
        
        try:
            await self.broadcast_pseudos()
            # Announce pseudo change if it's not a new connection
            if old_pseudo and old_pseudo != pseudo:
                await self.broadcast({
                    "type": "system",
                    "txt": f"{old_pseudo} is now known as {pseudo}"
                })
        except RuntimeError:
            await self.disconnect(websocket)

    async def broadcast(self, message: dict):
        # Store message in history if it's a chat message
        if message["type"] == "message":
            self.message_history.append({
                **message,
                "timestamp": datetime.now().isoformat()
            })
        
        failed_connections = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except RuntimeError:
                failed_connections.add(connection)
        
        # Clean up failed connections
        for failed in failed_connections:
            await self.disconnect(failed)

    async def broadcast_pseudos(self):
        pseudos = list(self.pseudos.values())
        await self.broadcast({"type": "pseudos", "pseudos": pseudos})

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            if msg_type == "pseudo":
                pseudo = data.get("txt")
                if pseudo:
                    await manager.receive_pseudo(websocket, pseudo)
            elif msg_type == "message":
                txt = data.get("txt")
                pseudo = data.get("pseudo")
                if txt and pseudo and websocket in manager.pseudos:
                    await manager.broadcast({
                        "type": "message",
                        "txt": txt,
                        "pseudo": pseudo
                    })
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except RuntimeError:
        await manager.disconnect(websocket)

if __name__ == "__main__":
    uvicorn.run("index:app", host="0.0.0.0", port=8000, reload=True)
