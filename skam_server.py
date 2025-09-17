import os
import asyncio
import uuid
from fastapi import FastAPI, WebSocket, HTTPException
import uvicorn
import asyncpg
from pydantic import BaseModel

app = FastAPI()
clients = set()
DATABASE_URL = os.environ.get('DATABASE_URL')

class UserAuth(BaseModel):
    name:str
    uuid:str
    user_id:int
    

@app.on_event('startup')
async def startup():
    app.state.pool = await asyncpg.create_pool(DATABASE_URL)
    
@app.on_event('shutdown')
async def shutdown():
    await app.state.pool.close()

@app.get("/", include_in_schema=False)
@app.head("/", include_in_schema=False)
async def healthcheck():
    return {"status": "ok"}

@app.post('/auth')
async def auth(user: UserAuth):

    query = 'SELECT id, name FROM users WHERE uuid = $1'
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(query, user.uuid)
    if row:
        return {'status': 'ok', 'name': row['name'], 'user_id': row['id']}
    else:
        raise HTTPException(status_code = 401, detail = 'User not found')
    

@app.post('/register')
async def register(user: UserAuth):
    if not user.name:
        raise HTTPException(status_code = 400, detail = 'Name rquired')
    user_uuid = str(uuid.uuid4())
    query = 'INSERT INTO users (uuid, name) VALUES ($1, $2) RETURNING id'
    async with app.state.pool.acquire() as conn:
        user_id = await conn.fetchval(query, user_uuid, user.name)
    return {'status': 'ok', 'user_id': user_id, 'uuid': user_uuid}

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    try:
        while True:
            msg = await ws.receive_text()
            for client in clients:
                if client is not ws:
                    await client.send_text(msg)
    except Exception:
        pass
    finally:
        clients.remove(ws)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
