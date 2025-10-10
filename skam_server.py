import logging
import os
import asyncio
import secrets
import nacl

from nacl.signing import SignedMessage, VerifyKey
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
active_chats = {}
logging.basicConfig(level = logging.INFO)
DATABASE_URL = os.environ.get('DATABASE_URL')
JWT_SECRET = os.environ.get('JWT_SECRET', 'secretkey228rfrfuhrs4fs')
JWT_ALGORITHM = 'HS256'

class AuthRequest(BaseModel):
    public_key:str | None = None
    
class AuthVerify(BaseModel):
    signed_message: str | None = None
    signed_seed: str | None = None
    public_key: str | None = None
    
class RegisterRequest(BaseModel):
    name: str | None = None
    public_key: str | None = None
    verify_key: str | None = None

class GetFriends(BaseModel):
    token: str | None = None
   
class AddFriend(BaseModel):
    token: str | None = None
    friend_id: int | None = None
 
class LoadMessages(BaseModel):
    token: str | None = None
    target_id: int | None = None

class GetPublic(BaseModel):
    target_id: int | None = None
    
class SetActive(BaseModel):
    token: str | None = None
    target_id: int | None = None

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
    logging.info(f'{user.signed_seed} \n {user.public_key} \n {user.signed_message}')
    
    signed_message = base64.b64decode(user.signed_message)
    signature = base64.b64decode(user.signed_seed)
    public_key = base64.b64decode(user.public_key)
    
    logging.info(f'{signature} {signed_message}')
    
    query = 'SELECT id, verify_key, nickname FROM users WHERE public_key = $1'
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(query, user.public_key)
    if not row:
        raise HTTPException(status_code = 401, detail = 'User not found')
    
    user_id = row['id']
    name = row['nickname']
    verify_key = base64.b64decode(row['verify_key'])
    
    if user.public_key not in challenges:
        return {'status': 'error'}
    
    try:
        logging.info(verify_key)
        verify_key = VerifyKey(verify_key)
        
        verify_key.verify(signed_message, signature)
        logging.info('Заебись')
        
        jwt = create_jwt(user_id)
        challenges.pop(user.public_key, None)
        return {'status': 'ok', 'token': jwt, 'id': user_id, 'name':name}
        
    except Exception as ex:
        logging.info(ex)
        return {'status': 'error'}
    
    

@app.post('/register')
async def register(user: RegisterRequest):
    if not user.name:
        raise HTTPException(status_code = 400, detail = 'Name rquired')
    if not user.public_key:
        raise HTTPException(status_code = 400, detail = 'Public key required')
    if not user.verify_key:
        raise HTTPException(status_code = 400, detail = 'Verify key required')
    query = 'INSERT INTO users (public_key, nickname, verify_key) VALUES ($1, $2, $3) RETURNING id'
    async with app.state.pool.acquire() as conn:
        user_id = await conn.fetchval(query, user.public_key, user.name, user.verify_key)
        
    if user_id:
        token = create_jwt(user_id)
        return {'status': 'ok', 'id': user_id, 'token':token}
    else:
        return JSONResponse(status_code = 401, content = {'status':'error', 'detail':'Unauthorized'})
    

@app.post('/friends')
async def get_friends(user: GetFriends):
    user_id = decode_jwt(user.token)
    query = 'SELECT friend_id, nickname FROM friends WHERE user_id = $1'
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(query, user_id)
    if not rows:
        return {'status':'lonely'}
    else:
        friends = [dict(row) for row in rows]
        return {'status':'ok', 'friends':friends}

@app.post('/addfriend')
async def addfr(user: AddFriend):
    user_id = decode_jwt(user.token)
    friend_id = user.friend_id
    query = 'SELECT nickname FROM users WHERE id = $1'
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(query,friend_id)
    if row['nickname'] is not None:
        query = 'INSERT INTO friends (user_id, friend_id, nickname) VALUES ($1, $2, $3)'
        async with app.state.pool.acquire() as conn:
            await conn.execute(query, user_id, friend_id, row['nickname'])
            return {'status':'ok'}
    else:
        raise HTTPException(status_code = 404, detail = 'User not found')
    
@app.post('/getpublic')
async def getpublic(user: GetPublic):
    logging.info('сюда зашёл')
    query = 'SELECT public_key FROM users WHERE id=$1'
    async with app.state.pool.acquire() as conn:
        public_key = await conn.fetchval(query, user.target_id)
    if public_key is not None:
        logging.info('vernul ok')
        return {'status': 'ok', 'public_key': public_key}
    else:
        return {'status': 'error'}

@app.post('/messages')
async def msgs(user: LoadMessages):
    user_id = decode_jwt(user.token)
    friend_id = user.target_id
    
    query = 'SELECT * FROM messages WHERE sender_id = $1 AND receiver_id = $2'
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(query, user_id, friend_id)
        if not rows:
            return {'status':'none', 'message':'сообщений нет'}
        else: 
            messages = [dict(row) for row in rows]
            return {'status':'ok', 'messages':messages}
        
@app.post('/setactive')
async def setactive(user: SetActive):
    user_id = decode_jwt(user.token)
    active_chats[user_id] = user.target_id
    return {'status':'ok'}
    
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


            if target_id in clients and active_chats[user_id] == target_id:
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
