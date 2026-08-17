"""复盘模式智能体对话路由:PLD /api/classify 语义路由(零副作用),
分类不可用或 general 意图→按数据修正兜底登记 chat 异议。"""
import asyncio

import agent_manager
from tests.test_agent_manager import FakeWS

SESSION = {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}


def make_mgr(monkeypatch, calls):
    async def fake_stream(msg, **kwargs):
        calls.append(msg)
        yield {"event_type": "complete", "payload": {}, "session_id": "s1"}

    async def fake_session(sid):
        return SESSION

    async def fake_classify(message, session_id=None):
        return {"intent_type": "general", "confidence": 1.0, "parameters": {}}

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    monkeypatch.setattr(agent_manager.pld_client, "classify", fake_classify)
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


async def test_keyword_miss_falls_back_to_data_correction(monkeypatch):
    """关键词门槛已移除:无关键词消息经 classify(general)仍按数据修正兜底登记。"""
    calls = []
    mgr = make_mgr(monkeypatch, calls)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "今天天气怎么样"})
    assert mgr.confirm_decisions["WindDiagnosisTool"] == {
        "decision": "chat", "value": "今天天气怎么样"}
    assert any(o.get("decision") == "chat" for o in mgr.objection_log)
    assert any(e["type"] == "objection_accepted" and e["agent"] == "wind"
               for e in ws.events)
    assert calls == []          # 未直接转发 PLD chat


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


RESULT_OK = {"event_type": "result", "payload": {
    "tool": "LightningDiagnosisTool",
    "output": {"structured_data": {"fault_type": "雷击-绕击", "confidence": 0.9,
                                   "evidence": ["证据A"]}, "raw_text": "raw"}},
    "session_id": "s1"}
COMPLETE = {"event_type": "complete", "payload": {
    "report": "# 复盘报告", "summary": {"fault_type": "雷击", "confidence": 0.9}},
    "session_id": "s1"}


def make_mgr_multistream(monkeypatch, calls, streams):
    iters = [iter(s) for s in streams]

    async def fake_stream(msg, **kwargs):
        calls.append(msg)
        for e in iters.pop(0):
            yield e

    async def fake_session(sid):
        return SESSION

    async def fake_classify(message, session_id=None):
        return {"intent_type": "general", "confidence": 1.0, "parameters": {}}

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    monkeypatch.setattr(agent_manager.pld_client, "classify", fake_classify)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    return mgr


async def test_chat_objection_during_review_wait_not_swallowed(monkeypatch):
    """F2 回归：报告审核等待期内登记的对话异议，「满意」不得吞掉/跨轮泄漏。

    满意应答时若 confirm_decisions 存在非 ok 决策 → 继续循环由异议分支整轮重跑；
    运行结束后 confirm_decisions 无残留。
    """
    calls = []
    # 流1=首轮诊断(defer)；流2=无异议终轮(生成报告,进入审核等待)；
    # 流3=对话异议（自由文本后缀）整轮重跑(defer)；流4=重跑后无异议终轮
    streams = [
        [{"event_type": "start", "payload": {}, "session_id": "s1"}, RESULT_OK, COMPLETE],
        [{"event_type": "start", "payload": {}, "session_id": "s1"}, RESULT_OK, COMPLETE],
        [{"event_type": "start", "payload": {}, "session_id": "s1"}, RESULT_OK, COMPLETE],
        [{"event_type": "start", "payload": {}, "session_id": "s1"}, RESULT_OK, COMPLETE],
    ]
    mgr = make_mgr_multistream(monkeypatch, calls, streams)
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.3)
        # 首轮逐项确认：无异议 → 进入报告审核等待
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.3)
        # 审核等待期内向诊断智能体发送关键词命中对话 → 登记 chat 异议
        await mgr.handle_message({"type": "chat", "agent": "lightning",
                                  "message": "这个数据不对，重新检查"})
        await asyncio.sleep(0.3)
        # 回答满意：异议必须被尊重（继续循环重跑），不得直接 break
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})
        await asyncio.sleep(0.4)
        # 重跑轮逐项确认：无异议
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.3)
        # 重跑轮审核：满意，正常结束
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    # 异议触发了整轮重跑（chat 异议为自由文本后缀）
    assert len(calls) == 4  # 首轮defer + 终轮 + 异议重跑defer + 重跑后终轮
    assert "复盘异议" in calls[2] and "这个数据不对，重新检查" in calls[2]
    # 运行结束后无残留非 ok 决策（不跨轮泄漏）
    assert not [d for d in mgr.confirm_decisions.values() if d.get("decision") != "ok"]
    assert any(e["type"] == "objection_accepted" for e in ws.events)
    assert any(e["type"] == "confirm_queue_clear" for e in ws.events)
    logs = [e["message"] for e in ws.events if e["type"] == "log"]
    assert any("未处理的对话异议" in m for m in logs)


async def test_review_satisfied_without_objection_breaks_normally(monkeypatch):
    """F2 对照：审核满意且无遗留异议 → 正常结束，不触发额外重跑。"""
    calls = []
    streams = [
        [{"event_type": "start", "payload": {}, "session_id": "s1"}, RESULT_OK, COMPLETE],
        # 无异议终轮(生成报告)
        [{"event_type": "start", "payload": {}, "session_id": "s1"}, RESULT_OK, COMPLETE],
    ]
    mgr = make_mgr_multistream(monkeypatch, calls, streams)
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.3)
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.3)
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    assert len(calls) == 2          # 首轮defer + 无异议终轮,无额外重跑
    assert mgr.confirm_decisions == {}


async def test_chat_objection_releases_pending_confirm(monkeypatch):
    """对话异议即视为该工具的确认：释放 pending_confirms，全部释放后确认轮完成。"""
    calls = []
    mgr = make_mgr(monkeypatch, calls)
    ws = FakeWS()
    await mgr.connect(ws)
    mgr.pending_confirms["LightningDiagnosisTool"] = {"tool": "LightningDiagnosisTool"}
    mgr._confirms_done = asyncio.Event()
    await mgr.handle_message({"type": "chat", "agent": "lightning",
                              "message": "把权重调整为0.1"})
    assert "LightningDiagnosisTool" not in mgr.pending_confirms
    assert mgr._confirms_done.is_set()


async def test_chat_objection_releases_only_that_tool(monkeypatch):
    """多工具待确认时，对话异议只释放本工具，确认轮不提前完成。"""
    calls = []
    mgr = make_mgr(monkeypatch, calls)
    ws = FakeWS()
    await mgr.connect(ws)
    mgr.pending_confirms["LightningDiagnosisTool"] = {"tool": "LightningDiagnosisTool"}
    mgr.pending_confirms["WindDiagnosisTool"] = {"tool": "WindDiagnosisTool"}
    mgr._confirms_done = asyncio.Event()
    await mgr.handle_message({"type": "chat", "agent": "lightning",
                              "message": "把权重调整为0.1"})
    assert "LightningDiagnosisTool" not in mgr.pending_confirms
    assert "WindDiagnosisTool" in mgr.pending_confirms
    assert not mgr._confirms_done.is_set()
