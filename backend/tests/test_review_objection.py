"""复盘报告审核：诊断类异议触发完整重跑；报告类异议仅改报告；空结果标记。"""
import asyncio
import agent_manager
from tests.test_agent_manager import FakeWS

RESULT_OK = {"event_type": "result", "payload": {
    "tool": "LightningDiagnosisTool",
    "output": {"structured_data": {"fault_type": "雷击-绕击", "confidence": 0.9,
                                   "evidence": ["证据A"]}, "raw_text": "raw"}},
    "session_id": "s1"}
RESULT_EMPTY = {"event_type": "result", "payload": {
    "tool": "WindDiagnosisTool", "output": {"structured_data": {}, "raw_text": ""}},
    "session_id": "s1"}
COMPLETE = {"event_type": "complete", "payload": {
    "report": "# 报告", "summary": {"fault_type": "雷击", "confidence": 0.9}},
    "session_id": "s1"}
SESSION = {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}


def make_mgr(monkeypatch, calls):
    async def fake_stream(msg, **kwargs):
        calls.append(msg)
        yield {"event_type": "start", "payload": {}, "session_id": "s1"}
        yield RESULT_OK
        yield COMPLETE

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    return mgr


async def test_diagnosis_objection_triggers_full_rerun(monkeypatch):
    calls = []
    mgr = make_mgr(monkeypatch, calls)
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.2)
        # 第一轮逐项确认
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.2)
        # 第一轮报告审核：诊断类异议
        await mgr.handle_message({"type": "report_review_response", "satisfied": False,
                                  "instruction": "雷电诊断要考虑地形", "kind": "diagnosis"})
        await asyncio.sleep(0.4)
        # 重跑后的逐项确认
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.2)
        # 重跑后的报告审核：满意
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    # 第二次诊断流携带异议上下文
    assert any("雷电诊断要考虑地形" in c and "复盘异议" in c for c in calls[1:])
    assert any(o["kind"] == "diagnosis_objection" for o in mgr.objection_log)
    reviews = [e for e in ws.events if e["type"] == "report_review_request"]
    assert len(reviews) == 2


async def test_report_objection_only_modifies_report(monkeypatch):
    calls = []
    mgr = make_mgr(monkeypatch, calls)
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.2)
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.2)
        await mgr.handle_message({"type": "report_review_response", "satisfied": False,
                                  "instruction": "删除第三章", "kind": "report"})
        await asyncio.sleep(0.2)
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    # 报告类异议原文下发，不加重跑前缀，不重跑诊断
    modify_calls = [c for c in calls if c == "删除第三章"]
    assert len(modify_calls) == 1 and "复盘异议" not in modify_calls[0]
    assert any(o["kind"] == "report_modify" for o in mgr.objection_log)


async def test_empty_result_flagged_in_confirm(monkeypatch):
    async def fake_stream(msg, **kwargs):
        yield {"event_type": "start", "payload": {}, "session_id": "s1"}
        yield RESULT_EMPTY
        yield COMPLETE

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.2)
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "WindDiagnosisTool", "decision": "recheck"})
        await asyncio.sleep(0.2)
        # recheck 异议触发整轮重跑：重跑再次弹出确认，本次无异议
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "WindDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.2)
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    confirms = [e for e in ws.events if e["type"] == "tool_confirm_request"]
    assert confirms[0]["empty"] is True
