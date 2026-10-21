"""FastAPI 入口：WebSocket 实时通道 + 健康检查。"""
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

import pld_client
import preview
from agent_manager import AgentManager

app = FastAPI(title="输电线路智能诊断全息指挥室")
app.include_router(preview.router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = AgentManager()


@app.get("/api/health")
def health():
    return {"status": "ok", "agents": manager.status}


@app.post("/api/templates/upload")
async def upload_template_proxy(file: UploadFile):
    data = await file.read()
    body = await pld_client.upload_template(data, file.filename or "template.md")
    # PLD 拒绝（格式不符等）时透传错误状态，让前端能提示
    ok = body.get("success", True) and not body.get("error")
    return JSONResponse(body, status_code=200 if ok else 400)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            data = await ws.receive_json()
            await manager.handle_message(data)
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8100, reload=True)


# ---------- 生产模式：托管前端构建产物 ----------
# dist 存在时由后端直接托管（ws.js 走 location.host 同源连接，无需 Node/Vite）。
# 路由注册顺序保证 /api/* 与 /ws 优先于 SPA 回退。
DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if DIST_DIR.is_dir():

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404)
        file = DIST_DIR / full_path
        if full_path and file.is_file():
            return FileResponse(file)
        return FileResponse(DIST_DIR / "index.html")
