"""PLDiagnosis 平台客户端：SSE 聊天流 + REST 会话/技能接口。"""
import json
from typing import AsyncIterator

import httpx

PLD_BASE = "http://localhost:5000"

_timeout = httpx.Timeout(connect=10, read=600, write=30, pool=10)


async def chat_stream(message: str) -> AsyncIterator[dict]:
    """调用 PLDiagnosis /chat，逐条产出 SSE 事件 dict。

    事件结构: {"event_type": start|thinking|content|status|complete|error, "payload": {...}, "session_id": ...}
    """
    async with httpx.AsyncClient(timeout=_timeout) as client:
        async with client.stream(
            "POST", f"{PLD_BASE}/chat", json={"message": message}
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
