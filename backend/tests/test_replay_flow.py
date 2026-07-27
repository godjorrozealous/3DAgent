import asyncio
import pytest
import agent_manager
from tests.test_agent_manager import FakeWS, make_manager  # tests 包内复用


RESULT_STREAM = [
    {"event_type": "start", "payload": {}, "session_id": "s1"},
    {"event_type": "result", "payload": {
        "tool": "LightningDiagnosisTool",
        "output": {"structured_data": {"fault_type": "雷击-绕击", "confidence": 0.985,
                                       "evidence": ["证据A"]}, "raw_text": "raw"}},
     "session_id": "s1"},
    {"event_type": "complete", "payload": {
        "report": "# 复盘报告", "summary": {"fault_type": "雷击-绕击", "confidence": 0.9}},
     "session_id": "s1"},
]

SESSION = {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}


def make_mgr(monkeypatch, sent):
    async def fake_stream(msg):
        sent.append(msg)
        for e in RESULT_STREAM:
            yield e

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    return mgr


async def test_replay_emits_confirm_and_dispatches_objection(monkeypatch):
    sent = []
    mgr = make_mgr(monkeypatch, sent)
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.3)
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool",
                                  "decision": "exclude"})
        assert mgr.confirm_decisions["LightningDiagnosisTool"]["decision"] == "exclude"

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    confirms = [e for e in ws.events if e["type"] == "tool_confirm_request"]
    assert len(confirms) == 1
    assert confirms[0]["tool"] == "LightningDiagnosisTool"
    assert confirms[0]["fault_type"] == "雷击-绕击"
    # 异议已下发（exclude 指令文本）
    assert any("排除" in m for m in sent[1:])  # sent[0] 是诊断消息本身


async def test_realtime_no_confirm(monkeypatch):
    sent = []
    mgr = make_mgr(monkeypatch, sent)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.run_diagnosis(replay=False)
    assert not [e for e in ws.events if e["type"] == "tool_confirm_request"]
