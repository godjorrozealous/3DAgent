"""复盘 defer_report：逐项确认轮只跑工具不出报告，全部无异议后终轮生成。

用户铁律(2026-08-17):复盘时必须逐项确认全部无异议,才允许驱动报告生成;
此前确认未完成报告已在流式生成,作废报告白跑 30-60s LLM。
"""
import asyncio

import agent_manager
from tests.test_agent_manager import FakeWS

RESULT_OK = {"event_type": "result", "payload": {
    "tool": "LightningDiagnosisTool",
    "output": {"structured_data": {"fault_type": "雷击-绕击", "confidence": 0.9,
                                   "evidence": ["证据A"]}, "raw_text": "raw"}},
    "session_id": "s1"}
COMPLETE_DEFERRED = {"event_type": "complete", "payload": {
    "report": "", "summary": {}, "report_deferred": True,
    "message": "工具诊断完成,等待逐项确认;全部无异议后生成报告。"},
    "session_id": "s1"}
COMPLETE_FINAL = {"event_type": "complete", "payload": {
    "report": "# 复盘报告", "summary": {"fault_type": "雷击", "confidence": 0.9}},
    "session_id": "s1"}
SESSION = {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}


def make_mgr(monkeypatch, calls):
    """fake PLD:按 defer_report kwarg 区分确认轮/终轮。"""

    async def fake_stream(msg, **kwargs):
        calls.append({"msg": msg, "defer_report": kwargs.get("defer_report", False)})
        yield {"event_type": "start", "payload": {}, "session_id": "s1"}
        yield RESULT_OK
        if kwargs.get("defer_report"):
            yield COMPLETE_DEFERRED
        else:
            yield COMPLETE_FINAL

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    return mgr


async def test_defer_rounds_generate_no_report_until_all_ok(monkeypatch):
    """确认轮(defer)不产出报告;全部无异议后终轮(不带 defer)才生成并进审核。"""
    calls = []
    mgr = make_mgr(monkeypatch, calls)
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.3)
        # 首轮逐项确认:无异议
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.4)
        # 报告审核:满意
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())

    # 首轮 defer,终轮不带 defer
    assert calls[0]["defer_report"] is True
    assert calls[-1]["defer_report"] is False
    # defer 轮不得覆盖报告:报告 done=True 只在终轮后出现
    done_reports = [e for e in ws.events
                    if e["type"] == "report" and e.get("done") and e.get("content")]
    assert len(done_reports) == 1
    assert done_reports[0]["content"] == "# 复盘报告"
    # 报告摘要在终轮后广播
    summaries = [e for e in ws.events if e["type"] == "report_summary"]
    assert len(summaries) == 1 and summaries[0]["kind"] == "replay"
    reviews = [e for e in ws.events if e["type"] == "report_review_request"]
    assert len(reviews) == 1


async def test_objection_rerun_also_defers(monkeypatch):
    """异议重跑轮同样 defer:确认未完成前任何一轮都不生成报告。"""
    calls = []
    mgr = make_mgr(monkeypatch, calls)
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.3)
        # 首轮:权重异议
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool",
                                  "decision": "weight", "value": 0.1})
        await asyncio.sleep(0.5)
        # 重跑轮:无异议
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.4)
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())

    defer_calls = [c for c in calls if c["defer_report"]]
    # 非 defer 调用 = 结构化命令(defer_rediagnose 通道) + 终轮;终轮是裸诊断消息
    final_calls = [c for c in calls
                   if not c["defer_report"] and "权重调整" not in c["msg"]]
    # 首轮 + 异议重跑轮均 defer
    assert len(defer_calls) == 2
    assert len(final_calls) == 1  # 仅终轮生成报告
    # 确认完成前不得有任何完整报告广播
    assert mgr.last_report == "# 复盘报告"


async def test_deferred_complete_waits_confirm_before_review(monkeypatch):
    """关键时序:defer 轮 complete 到达但用户尚未确认时,不得进入报告审核。"""
    calls = []
    mgr = make_mgr(monkeypatch, calls)
    ws = FakeWS()
    await mgr.connect(ws)

    confirmed = asyncio.Event()

    async def respond():
        # 等 defer 轮 complete 已处理(确认弹窗已弹出),故意拖延确认
        await asyncio.sleep(0.5)
        reviews_before = [e for e in ws.events if e["type"] == "report_review_request"]
        assert not reviews_before, "未确认就进入报告审核"
        confirmed.set()
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.4)
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    assert confirmed.is_set()
    reviews = [e for e in ws.events if e["type"] == "report_review_request"]
    assert len(reviews) == 1
