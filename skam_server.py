import asyncio
import websockets
import os

clients=()

async def handler(websocket, path):
    clients.add(websocket)
    try:
        async for message in websocket:
            for client in clients:
                if client != websocket:
                    await client.send(message)
    finally:
        clients.remove(websocket)
        
async def main():
    port = int(os.environ.get('PORT',10000))
    async with websockets.serve(handler,'0.0.0.0',port):
        print(f'Server started on port {port}')
        await asyncio.Future()
    
if __name__ == '__main__':
    asyncio.run(main())