"""复盘重跑 v2：结构化异议单独下发 + 裸诊断消息重跑 + 空完成守卫。"""
import asyncio
import agent_manager
from tests.test_agent_manager import FakeWS

RESULT_OK = {"event_type": "result", "payload": {
    "tool": "LightningDiagnosisTool",
    "output": {"structured_data": {"fault_type": "雷击-绕击", "confidence": 0.9,
                                   "evidence": ["证据A"]}, "raw_text": "raw"}},
    "session_id": "s1"}
COMPLETE = {"event_type": "complete", "payload": {
    "report": "# 复盘报告", "summary": {"fault_type": "雷击", "confidence": 0.9}},
    "session_id": "s1"}
COMPLETE_EMPTY = {"event_type": "complete", "payload": {"report": "", "summary": {}},
                  "session_id": "s1"}
SESSION = {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}


def make_mgr(monkeypatch, calls, streams):
    iters = [iter(s) for s in streams]

    async def fake_stream(msg):
        calls.append(msg)
        for e in iters.pop(0):
            yield e

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    return mgr


async def test_weight_objection_structured_cmd_then_bare_rerun(monkeypatch):
    """权重异议：先发独立命令，再发裸诊断消息（不带异议后缀）重跑。"""
    calls = []
    # 流1=首轮诊断, 流2=weight命令(adjust_weight 完成), 流3=裸诊断重跑
    streams = [
        [{"event_type": "start", "payload": {}, "session_id": "s1"}, RESULT_OK, COMPLETE],
        [{"event_type": "complete", "payload": {"message": "ok"}, "session_id": "s1"}],
        [{"event_type": "start", "payload": {}, "session_id": "s1"}, RESULT_OK, COMPLETE],
    ]
    mgr = make_mgr(monkeypatch, calls, streams)
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.3)
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool",
                                  "decision": "weight", "value": 0.1})
        await asyncio.sleep(0.4)
        # 重跑轮确认（无异议）
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.3)
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    assert calls[1] == "将LightningDiagnosisTool权重调整为0.1"
    assert calls[2] == calls[0]                      # 裸诊断消息
    assert "复盘异议" not in calls[2]
    # 重跑前复位了前端确认状态
    assert any(e["type"] == "confirm_queue_clear" for e in ws.events)


async def test_empty_complete_keeps_last_valid_report(monkeypatch):
    """重跑 complete 无报告（PLD 误判意图）：保留上轮报告，审核询问 empty=False。"""
    calls = []
    streams = [
        [{"event_type": "start", "payload": {}, "session_id": "s1"}, RESULT_OK, COMPLETE],
        [{"event_type": "complete", "payload": {"message": "ok"}, "session_id": "s1"}],
        [{"event_type": "start", "payload": {}, "session_id": "s1"}, COMPLETE_EMPTY],
    ]
    mgr = make_mgr(monkeypatch, calls, streams)
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.3)
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool",
                                  "decision": "weight", "value": 0.1})
        await asyncio.sleep(0.4)
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    assert mgr.last_report == "# 复盘报告"
    reviews = [e for e in ws.events if e["type"] == "report_review_request"]
    assert reviews and reviews[-1]["empty"] is False
    assert any("未产出报告" in e.get("message", "") for e in ws.events if e["type"] == "log")
