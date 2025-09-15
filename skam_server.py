import os
import asyncio
from fastapi import FastAPI, WebSocket
import uvicorn

app = FastAPI()
clients = set()

@app.get("/")
async def healthcheck():
    return {"status": "ok"}

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    try:
        while True:
            msg = await ws.receive_text()
            for client in clients:
                if client != ws:
                    await client.send_text(msg)
    except Exception:
        pass
    finally:
        clients.remove(ws)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
