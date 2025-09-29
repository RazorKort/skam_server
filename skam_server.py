import logging
import os
import asyncio
import secrets
import nacl

from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError
import base64

from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
import asyncpg
from pydantic import BaseModel
import jwt

app = FastAPI()
clients = {}
challenges = {}
logging.basicConfig(level = logging.INFO)
DATABASE_URL = os.environ.get('DATABASE_URL')
JWT_SECRET = os.environ.get('JWT_SECRET', 'secretkey228rfrfuhrs4fs')
JWT_ALGORITHM = 'HS256'

class AuthRequest(BaseModel):
    public_key:str | None = None
    
class AuthVerify(BaseModel):
    signed_seed: str | None = None
    public_key: str | None = None
    
class RegisterRequest(BaseModel):
    name: str | None = None
    public_key: str | None = None
    

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

@app.post('/auth-request')
async def auth(user: AuthRequest):

    query = 'SELECT id FROM users WHERE public_key = $1'
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(query, user.public_key)
    if not row:
        raise HTTPException(status_code = 401, detail = 'User not found')
        
    else:
        seed = secrets.token_urlsafe(32)
        challenges[user.public_key] = seed
        return {'status': 'ok', 'seed': seed}
 
    
@app.post('/auth-verify')
async def auth(user: AuthVerify):
    query = 'SELECT id FROM users WHERE public_key = $1'
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(query, user.public_key)
    if not row:
        raise HTTPException(status_code = 401, detail = 'User not found')
    user_id = row['id']
    if user.public_key not in challenges:
        return {'status': 'error'}
    try:
        verify_key = VerifyKey(base64.b64decode(user.public_key))
        signature_bytes = base64.b64decode(user.signed_seed)
        seed = challenges[user.public_key]
        verify_key.verify(seed.encode, signature_bytes)
        jwt = create_jwt(user_id)
        challenges.pop(user.public_key, None)
        return {'status': 'ok', 'token': jwt, 'id': user_id}
        
    except BadSignatureError:
        return {'status': 'error'}
    
    

@app.post('/register')
async def register(user: RegisterRequest):
    if not user.name:
        raise HTTPException(status_code = 400, detail = 'Name rquired')
    query = 'INSERT INTO users (public_key, nickname) VALUES ($1, $2) RETURNING id'
    async with app.state.pool.acquire() as conn:
        user_id = await conn.fetchval(query, user.public_key, user.name)
        
    if user_id:
        token = create_jwt(user_id)
        return {'status': 'ok', 'id': user_id, 'token':token}
    else:
        return JSONResponse(status_code = 401, content = {'status':'error', 'detail':'Unauthorized'})
    

@app.post('/friends')
async def get_friends(token: str):
    user_id = decode_jwt(token)
    query = 'SELECT friend_id, nickname FROM friends WHERE user_id = $1'
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(query, user_id)
    if not rows:
        return {'status':'lonely'}
    else:
        friends = [dict(row) for row in rows]
        return {'status':'ok', 'friends':friends}

@app.post('/addfr')
async def addfr(token: str, friend_id: int):
    user_id = decode_jwt(token)
    query = 'SELECT nickname FROM users WHERE id = $1'
    async with app.state.pool.acquire() as conn:
        name = await conn.fetchval(query,friend_id)
    if name is not None:
        query = 'INSERT INTO friends (user_id, friend_id, nickname) VALUES ($1, $2, $3)'
        async with app.state.pool.acquire() as conn:
            await conn.execute(query, user_id, friend_id, name)
            return {'status':'ok'}
    else:
        raise HTTPException(status_code = 404, detail = 'User not found')
    
@app.post('/msgs')
async def msgs(token: str, friend_id: int):
    user_id = decode_jwt(token)
    query = 'SELECT * FROM messages WHERE sender_id = $1 AND receiver_id = $2'
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(query, user_id, friend_id)
        if not rows:
            return {'status':'none', 'message':'сообщений нет'}
        else: 
            messages = [dict(row) for row in rows]
            return {'status':'ok', 'messages':messages}
    
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token:str):
    try:
        user_id = decode_jwt(token)
    except HTTPException:
        await ws.close(code = 1008)
        return
    await ws.accept()
    clients[user_id] = ws
    try:
        while True:
            msg_data = await ws.receive_json()
            target_id = msg_data.get('target_id')
            message = msg_data.get('message')
            name = msg_data.get('name')
            logging.info(f'{target_id}, {name}, {message}')
            
            query = 'INSERT INTO messages (sender_id, receiver_id, message, name) VALUES ($1, $2, $3, $4)'
            async with app.state.pool.acquire() as conn:
                await conn.fetch(query, user_id, target_id, message, name)


            if target_id in clients:
                await clients[target_id].send_json({'from':user_id, 'message':message, 'name':name})

    except Exception:
        pass
    finally:
        clients.pop(user_id, None)

def create_jwt(user_id: int):
    payload = {'user_id': user_id}
    return jwt.encode(payload, JWT_SECRET, algorithm = JWT_ALGORITHM)

def decode_jwt(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload['user_id']
    except jwt.PyJWTError:
        raise HTTPException(status_code = 401, detail = 'Invalid token')


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
