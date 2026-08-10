import asyncio
import agent_manager
from tests.test_agent_manager import FakeWS

async def test_chat_rejected_during_realtime_run(monkeypatch):
    gate = asyncio.Event()
    async def fake_stream(msg, **kwargs):
        yield {"event_type": "start", "payload": {}, "session_id": "s1"}
        await gate.wait()
        yield {"event_type": "complete", "payload": {"report": "r", "summary": {}}, "session_id": "s1"}
    async def fake_session(sid):
        return {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}
    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    ws = FakeWS()
    await mgr.connect(ws)
    task = asyncio.create_task(mgr.run_diagnosis(replay=False))
    await asyncio.sleep(0.1)
    await mgr.handle_message({"type": "chat", "agent": "commander", "message": "排除鸟害工具"})
    chats = [e for e in ws.events if e.get("type") == "chat"]
    assert any("不接受干预" in c.get("message", "") for c in chats)
    states = [e for e in ws.events if e.get("type") == "run_state"]
    assert states[0]["mode"] == "realtime"
    gate.set()
    await task
    states = [e for e in ws.events if e.get("type") == "run_state"]
    assert states[-1]["mode"] is None
