"""Loopback-only web entry point: python -m zelvo.api. No cloud services."""
from contextlib import asynccontextmanager
import asyncio
import json
import time
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from zelvo.live import DemoSettings, SessionManager, ROOT


def origin_allowed(origin, url):
    # Also support a separately bound local preview port. Never trust an
    # arbitrary Host header as an allowed origin: require a loopback hostname.
    return not origin or origin in ('http://127.0.0.1:5173','http://localhost:5173',
                                    'http://127.0.0.1:8000','http://localhost:8000') or (
        url.hostname in ('127.0.0.1','localhost') and origin == f'http://{url.netloc}')


def create_app(manager=None):
    manager = manager or SessionManager()

    @asynccontextmanager
    async def lifespan(app):
        # Parse once outside the request loop so the first click is responsive.
        await asyncio.to_thread(manager.get_geometry)
        yield
        await manager.close()

    app = FastAPI(title='ZELVO local live comparison',lifespan=lifespan)
    app.state.manager = manager

    @app.middleware('http')
    async def local_origin(request: Request, call_next):
        origin = request.headers.get('origin')
        if not origin_allowed(origin,request.url):
            return JSONResponse({'detail':'Use the local ZELVO page to control simulations.'},status_code=403)
        return await call_next(request)

    @app.get('/api/health')
    def health():
        return {'status':'ok','engine':'SUMO 1.26.0','mode':'local','model':'400-tree predictor'}

    @app.get('/api/network')
    def network(corridor: Literal['reference','expanded','curated'] = 'reference'):
        return manager.get_geometry(corridor)

    @app.post('/api/sessions',status_code=201)
    async def create(settings: DemoSettings):
        try:
            session = manager.create(settings)
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        return {'id':session.id,'status':session.status,'inputs':session.receipt}

    def get(session_id):
        if session_id not in manager.sessions:
            raise HTTPException(404,'Comparison not found. Start a new comparison.')
        return manager.sessions[session_id]

    @app.get('/api/sessions/{session_id}')
    def status(session_id: str):
        return get(session_id).summary()

    @app.get('/api/sessions/{session_id}/receipt')
    def receipt(session_id: str):
        return JSONResponse(get(session_id).summary(),headers={
            'Content-Disposition':f'attachment; filename="zelvo-{session_id[:8]}-receipt.json"'})

    @app.delete('/api/sessions/{session_id}',status_code=202)
    async def cancel(session_id: str):
        session = get(session_id)
        if session.status in ('starting','running'):
            session.cancel()
        return {'id':session.id,'status':session.status}

    @app.websocket('/api/sessions/{session_id}/stream')
    async def stream(socket: WebSocket,session_id: str):
        origin = socket.headers.get('origin')
        if not origin_allowed(origin,socket.url):
            await socket.close(code=1008)
            return
        if session_id not in manager.sessions:
            await socket.close(code=1008)
            return
        session = manager.sessions[session_id]
        await socket.accept()
        session.clients += 1
        session.last_client = time.monotonic()
        cursors = {'baseline':0,'zelvo':0}
        try:
            await socket.send_json({'type':'session','id':session.id,'inputs':session.receipt})
            while True:
                for side in cursors:
                    batch = session.frames[side][cursors[side]:cursors[side]+100]
                    if batch:
                        await socket.send_json({'type':'frames','side':side,'frames':batch})
                        cursors[side] += len(batch)
                caught_up = all(cursors[s]==len(session.frames[s]) for s in cursors)
                terminal = session.status not in ('running','starting') and session.task.done()
                if terminal and caught_up:
                    await socket.send_json({'type':'finished',**session.summary()})
                    break
                # Receive heartbeat and promptly detect disconnect, even before frames exist.
                try:
                    message = await asyncio.wait_for(socket.receive_text(),timeout=.1)
                    if message=='ping':
                        await socket.send_json({'type':'pong'})
                except asyncio.TimeoutError:
                    pass
        except WebSocketDisconnect:
            pass
        finally:
            session.clients -= 1
            session.last_client = time.monotonic()

    built = ROOT/'frontend/dist'
    if built.is_dir():
        app.mount('/',StaticFiles(directory=built,html=True),name='web')
    return app


app = create_app()

if __name__=='__main__':
    import uvicorn
    uvicorn.run('zelvo.api:app',host='127.0.0.1',port=8000,workers=1)
