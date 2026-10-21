"""PLDiagnosis 平台客户端：SSE 聊天流 + REST 会话/技能接口。"""
import json
import os
from typing import AsyncIterator

import httpx

# PLD 平台地址：默认同机 6000 端口（避开内网 5000 占用），可用 PLD_BASE 覆盖
PLD_BASE = os.getenv("PLD_BASE", "http://localhost:6000")

_timeout = httpx.Timeout(connect=10, read=600, write=30, pool=10)


async def chat_stream(message: str, *, session_id: str | None = None,
                      defer_rediagnose: bool = False,
                      data_overrides: dict | None = None,
                      defer_report: bool = False) -> AsyncIterator[dict]:
    """调用 PLDiagnosis /chat，逐条产出 SSE 事件 dict。

    事件结构: {"event_type": start|thinking|content|status|complete|error, "payload": {...}, "session_id": ...}
    session_id / defer_rediagnose / defer_report 为复盘编排通道参数，缺省不携带。
    defer_report: 逐项确认轮只执行工具不出报告，全部无异议后发终轮(不带 defer)生成。
    """
    body: dict = {"message": message}
    if session_id:
        body["session_id"] = session_id
    if defer_rediagnose:
        body["defer_rediagnose"] = True
    if data_overrides:
        body["data_overrides"] = data_overrides
    if defer_report:
        body["defer_report"] = True
    async with httpx.AsyncClient(timeout=_timeout) as client:
        async with client.stream(
            "POST", f"{PLD_BASE}/chat", json=body
        ) as resp:
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                try:
                    yield json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue


async def list_sessions() -> list[dict]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{PLD_BASE}/api/sessions")
        resp.raise_for_status()
        return resp.json().get("sessions", [])


async def get_session(session_id: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{PLD_BASE}/api/sessions/{session_id}")
        resp.raise_for_status()
        return resp.json()


async def reset_session(session_id: str) -> dict:
    """复位卡死在 diagnosing 的 PLD 会话（诊断流中断导致状态滞留）。"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{PLD_BASE}/api/sessions/{session_id}/reset")
        return resp.json()


async def get_active_session() -> dict | None:
    """取最近更新的会话作为当前会话。"""
    sessions = await list_sessions()
    if not sessions:
        return None
    sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    sid = sessions[0].get("session_id")
    return await get_session(sid) if sid else None


async def save_skill(name: str, content: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{PLD_BASE}/api/skills", json={"name": name, "content": content}
        )
        return resp.json()


async def delete_skill(name: str) -> dict:
    async with httpx.AsyncClient(base_url=PLD_BASE, timeout=30) as c:
        return (await c.delete(f"/api/skills/{name}")).json()


# ---------- 策略（技能） ----------
async def list_skills() -> dict:
    async with httpx.AsyncClient(base_url=PLD_BASE, timeout=30) as c:
        return (await c.get("/api/skills")).json()


async def get_default_skill() -> dict:
    async with httpx.AsyncClient(base_url=PLD_BASE, timeout=30) as c:
        return (await c.get("/api/skills/default")).json()


async def set_default_skill(name: str) -> dict:
    async with httpx.AsyncClient(base_url=PLD_BASE, timeout=30) as c:
        return (await c.post("/api/skills/default", json={"name": name})).json()


async def reset_skills() -> dict:
    async with httpx.AsyncClient(base_url=PLD_BASE, timeout=30) as c:
        return (await c.post("/api/skills/reset")).json()


# ---------- 模板 ----------
async def list_templates() -> dict:
    async with httpx.AsyncClient(base_url=PLD_BASE, timeout=30) as c:
        return (await c.get("/api/templates")).json()


async def upload_template(file_bytes: bytes, filename: str) -> dict:
    async with httpx.AsyncClient(base_url=PLD_BASE, timeout=60) as c:
        files = {"file": (filename, file_bytes)}
        return (await c.post("/api/templates/upload", files=files)).json()


async def activate_template(name: str) -> dict:
    async with httpx.AsyncClient(base_url=PLD_BASE, timeout=30) as c:
        return (await c.post("/api/templates/activate", json={"template_name": name})).json()


async def delete_template(name: str) -> dict:
    async with httpx.AsyncClient(base_url=PLD_BASE, timeout=30) as c:
        return (await c.delete(f"/api/templates/{name}")).json()


async def classify(message: str, session_id: str | None = None) -> dict:
    """调用 PLD /api/classify 纯意图分类(零副作用)。"""
    body: dict = {"message": message}
    if session_id:
        body["session_id"] = session_id
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{PLD_BASE}/api/classify", json=body)
        resp.raise_for_status()
        return resp.json()


async def history_relation(session_id: str) -> dict:
    """调用 PLD /api/history-relation 知识库历史关联。

    KB 串行两问、每问 timeout=300，最坏约 600s 才整体返回；超时给 660s 余量，
    避免长等待被误判为失败/端口失效（PLD 侧有会话级缓存，重问秒回）。
    """
    async with httpx.AsyncClient(timeout=660) as client:
        resp = await client.post(
            f"{PLD_BASE}/api/history-relation", json={"session_id": session_id}
        )
        resp.raise_for_status()
        return resp.json()
