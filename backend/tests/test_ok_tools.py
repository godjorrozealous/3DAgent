"""ok_tools 跨轮无异议记忆 + 重跑透传 data_overrides。"""
import asyncio

import agent_manager
from tests.test_agent_manager import FakeWS

RESULT_WIND = {"event_type": "result", "session_id": "s1", "payload": {
    "tool": "WindDiagnosisTool",
    "output": {"raw_text": "风偏报告", "structured_data": {
        "fault_type": "风偏", "confidence": 0.8, "evidence": ["e"]}}}}
RESULT_LIGHTNING = {"event_type": "result", "session_id": "s1", "payload": {
    "tool": "LightningDiagnosisTool",
    "output": {"raw_text": "雷电报告", "structured_data": {
        "fault_type": "雷击", "confidence": 0.9, "evidence": ["e"]}}}}
COMPLETE = {"event_type": "complete", "session_id": "s1", "payload": {
    "report": "# 报告", "summary": {"fault_type": "雷击", "confidence": 0.9}}}
SESSION = {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}


def make_mgr(monkeypatch, events, captured=None):
    async def fake_stream(msg, **kwargs):
        if captured is not None:
            captured.update(kwargs)
        for e in events:
            yield e

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    return mgr


async def test_ok_tool_auto_confirmed_on_rerun(monkeypatch):
    """重跑时 ok_tools 内工具:不广播确认弹窗,自动登记 ok 决策。"""
    mgr = make_mgr(monkeypatch, [RESULT_WIND, COMPLETE])
    mgr.ok_tools.add("WindDiagnosisTool")
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    summary = await mgr._stream_run("msg", True, {}, session_id="s1")
    assert not summary.get("_invalid")
    assert mgr.confirm_decisions["WindDiagnosisTool"]["decision"] == "ok"
    assert "WindDiagnosisTool" not in mgr.pending_confirms
    assert not any(e["type"] == "tool_confirm_request" for e in ws.events)


async def test_non_ok_tool_still_asks(monkeypatch):
    """不在 ok_tools 的工具:照常广播确认弹窗。"""
    mgr = make_mgr(monkeypatch, [RESULT_WIND, RESULT_LIGHTNING, COMPLETE])
    mgr.ok_tools.add("WindDiagnosisTool")
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.1)
        await mgr.handle_message({
            "type": "tool_confirm_response", "tool": "LightningDiagnosisTool",
            "decision": "ok"})

    await asyncio.gather(mgr._stream_run("msg", True, {}, session_id="s1"), respond())
    reqs = [e for e in ws.events if e["type"] == "tool_confirm_request"]
    assert [r["tool"] for r in reqs] == ["LightningDiagnosisTool"]


async def test_confirm_ok_populates_and_objection_discards(monkeypatch):
    """弹窗选无异议 → 进 ok_tools;对话异议 → 移出 ok_tools。"""
    mgr = make_mgr(monkeypatch, [])
    mgr.pending_confirms["WindDiagnosisTool"] = {"type": "tool_confirm_request"}
    await mgr.handle_message({
        "type": "tool_confirm_response", "tool": "WindDiagnosisTool", "decision": "ok"})
    assert "WindDiagnosisTool" in mgr.ok_tools
    mgr.pending_confirms["LightningDiagnosisTool"] = {"type": "tool_confirm_request"}
    await mgr.handle_message({
        "type": "tool_confirm_response", "tool": "LightningDiagnosisTool",
        "decision": "weight", "value": 0.1})
    assert "LightningDiagnosisTool" not in mgr.ok_tools

    async def fake_classify(message, session_id=None):
        return {"intent_type": "general", "confidence": 1.0, "parameters": {}}

    monkeypatch.setattr(agent_manager.pld_client, "classify", fake_classify)
    await mgr._replay_agent_chat("wind", "风速15m/s")
    assert "WindDiagnosisTool" not in mgr.ok_tools


async def test_ok_tools_cleared_on_new_run(monkeypatch):
    """每次新诊断/复盘开跑:ok_tools 清零(从零记忆)。"""
    mgr = make_mgr(monkeypatch, [COMPLETE])
    mgr.ok_tools.add("WindDiagnosisTool")
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.run_diagnosis(replay=False)
    assert mgr.ok_tools == set()


async def test_rerun_passes_data_overrides(monkeypatch):
    """复盘流携带 value_overrides → chat_stream 收到 data_overrides 透传。"""
    captured = {}
    mgr = make_mgr(monkeypatch, [COMPLETE], captured=captured)
    mgr.value_overrides["WindDiagnosisTool"] = "风速15m/s"
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr._stream_run("msg", True, {}, session_id="s1")
    assert captured["data_overrides"] == {"WindDiagnosisTool": "风速15m/s"}


async def test_realtime_run_without_overrides_omits_field(monkeypatch):
    """实时诊断或无改值:不携带 data_overrides(行为不变)。"""
    captured = {}
    mgr = make_mgr(monkeypatch, [COMPLETE], captured=captured)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr._stream_run("msg", False, {})
    assert "data_overrides" not in captured
