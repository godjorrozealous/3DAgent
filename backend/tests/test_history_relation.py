"""history_relation 路由:成功广播 sections;vendor 失败广播 error。"""
import agent_manager
from tests.test_agent_manager import FakeWS


async def areturn(v):
    return v


async def _raise(*a, **kw):
    raise ConnectionError("PLD 8503 不可达")


async def test_history_relation_success(monkeypatch):
    monkeypatch.setattr(agent_manager.pld_client, "history_relation",
                        lambda sid: areturn({"success": True,
                                             "sections": [{"title": "一、雅湖线历年情况", "answer": "……"}]}))
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.handle_message({"type": "history_relation"})
    ev = [e for e in ws.events if e["type"] == "history_relation"][0]
    assert ev["sections"][0]["title"].startswith("一、")


async def test_history_relation_error(monkeypatch):
    monkeypatch.setattr(agent_manager.pld_client, "history_relation", _raise)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.handle_message({"type": "history_relation"})
    ev = [e for e in ws.events if e["type"] == "history_relation"][0]
    assert "error" in ev


async def test_history_relation_no_session(monkeypatch):
    mgr = agent_manager.AgentManager()
    mgr.session_id = None
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.handle_message({"type": "history_relation"})
    ev = [e for e in ws.events if e["type"] == "history_relation"][0]
    assert ev["error"] == "无活跃会话"
