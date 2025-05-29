from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from typing import List, Dict
from collections import deque
from datetime import datetime

app = FastAPI()

# Allow CORS for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.pseudos: Dict[WebSocket, str] = {}
        self.message_history = deque(maxlen=100)  # Store last 100 messages

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        # Send message history to new client
        if self.message_history:
            await websocket.send_json({
                "type": "history",
                "messages": list(self.message_history)
            })

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.pseudos:
            del self.pseudos[websocket]

    async def receive_pseudo(self, websocket: WebSocket, pseudo: str):
        old_pseudo = self.pseudos.get(websocket)
        self.pseudos[websocket] = pseudo
        await self.broadcast_pseudos()
        # Announce pseudo change if it's not a new connection
        if old_pseudo and old_pseudo != pseudo:
            await self.broadcast({
                "type": "system",
                "txt": f"{old_pseudo} is now known as {pseudo}"
            })

    async def broadcast(self, message: dict):
        # Store message in history if it's a chat message
        if message["type"] == "message":
            self.message_history.append({
                **message,
                "timestamp": datetime.now().isoformat()
            })
        for connection in self.active_connections:
            await connection.send_json(message)

    async def broadcast_pseudos(self):
        pseudos = list(self.pseudos.values())
        await self.broadcast({"type": "pseudos", "pseudos": pseudos})

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        pseudo_received = False
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            if msg_type == "pseudo":
                pseudo = data.get("txt")
                if pseudo:
                    await manager.receive_pseudo(websocket, pseudo)
                    pseudo_received = True
            elif msg_type == "message":
                txt = data.get("txt")
                pseudo = data.get("pseudo")
                if txt and pseudo:
                    await manager.broadcast({
                        "type": "message",
                        "txt": txt,
                        "pseudo": pseudo
                    })
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        if websocket in manager.pseudos:
            old_pseudo = manager.pseudos[websocket]
            await manager.broadcast({
                "type": "system",
                "txt": f"{old_pseudo} has left the chat"
            })
        await manager.broadcast_pseudos()

if __name__ == "__main__":
    uvicorn.run("index:app", host="0.0.0.0", port=8000, reload=True)
