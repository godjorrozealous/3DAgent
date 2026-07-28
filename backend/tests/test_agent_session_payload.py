import agent_manager
from tests.test_agent_manager import FakeWS
from tests.test_replay_flow import RESULT_STREAM, SESSION

async def test_confirm_request_carries_full_payload(monkeypatch):
    async def fake_stream(msg):
        for e in RESULT_STREAM:
            yield e
    async def fake_session(sid):
        return SESSION
    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)
    import asyncio
    async def respond():
        await asyncio.sleep(0.3)
        await mgr.handle_message({"type": "tool_confirm_response", "tool": "LightningDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.3)
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})
    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    req = [e for e in ws.events if e.get("type") == "tool_confirm_request"][0]
    assert req["raw_text"] == "raw"
    assert req["structured_data"]["fault_type"] == "雷击-绕击"

async def test_subagent_chat_forwarded_with_context_prefix(monkeypatch):
    sent = []
    async def fake_stream(msg):
        sent.append(msg)
        yield {"event_type": "complete", "payload": {"message": "收到"}, "session_id": "s1"}
    async def fake_session(sid):
        return SESSION
    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    await mgr.handle_chat("lightning", "查询 19:40~19:50 的雷电数据")
    assert "【当前会话：" in sent[0] and "LightningDiagnosisTool" in sent[0]
    assert "查询 19:40~19:50" in sent[0]
