"""复盘模式智能体对话路由：关键词命中→异议；未命中→固定提示不转发 PLD。"""
import agent_manager
from tests.test_agent_manager import FakeWS

SESSION = {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}


def make_mgr(monkeypatch, calls):
    async def fake_stream(msg):
        calls.append(msg)
        yield {"event_type": "complete", "payload": {}, "session_id": "s1"}

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    mgr._run_replay = True
    return mgr


async def test_keyword_hit_becomes_chat_objection(monkeypatch):
    calls = []
    mgr = make_mgr(monkeypatch, calls)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "lightning",
                              "message": "把权重调整为0.1"})
    assert mgr.confirm_decisions["LightningDiagnosisTool"] == {
        "decision": "chat", "value": "把权重调整为0.1"}
    assert any(o.get("decision") == "chat" for o in mgr.objection_log)
    assert any(e["type"] == "objection_accepted" and e["agent"] == "lightning"
               for e in ws.events)
    chats = [e for e in ws.events if e["type"] == "chat" and e.get("from") == "agent"]
    assert any("统一上报司令" in e["message"] for e in chats)
    assert calls == []          # 未直接转发 PLD


async def test_keyword_miss_gets_fixed_hint(monkeypatch):
    calls = []
    mgr = make_mgr(monkeypatch, calls)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "今天天气怎么样"})
    assert mgr.confirm_decisions == {}
    chats = [e for e in ws.events if e["type"] == "chat" and e.get("from") == "agent"]
    assert any("仅受理与本轮诊断相关的异议" in e["message"] for e in chats)
    assert calls == []


async def test_ok_click_does_not_override_chat_objection(monkeypatch):
    calls = []
    mgr = make_mgr(monkeypatch, calls)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "lightning",
                              "message": "这个数据不对，重新检查"})
    # 随后点「无异议」不得吞掉已登记的对话异议
    mgr.pending_confirms["LightningDiagnosisTool"] = {"tool": "LightningDiagnosisTool"}
    mgr._confirms_done = None
    await mgr.handle_message({"type": "tool_confirm_response",
                              "tool": "LightningDiagnosisTool", "decision": "ok"})
    assert mgr.confirm_decisions["LightningDiagnosisTool"]["decision"] == "chat"
