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
    async def fake_stream(msg, **kwargs):
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
        await asyncio.sleep(0.3)
        # 异议触发整轮重跑：重跑流再次弹出逐项确认，本次无异议
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool",
                                  "decision": "ok"})
        await asyncio.sleep(0.3)
        # 全部无异议后的报告审核询问:直接满意,结束审核循环
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    confirms = [e for e in ws.events if e["type"] == "tool_confirm_request"]
    assert len(confirms) == 2  # 首轮 + 异议重跑轮各一次
    assert confirms[0]["tool"] == "LightningDiagnosisTool"
    assert confirms[0]["fault_type"] == "雷击-绕击"
    # exclude 为结构化异议：先独立命令下发，再裸诊断消息重跑
    assert sent[1] == "排除LightningDiagnosisTool"
    assert sent[2] == sent[0] and "复盘异议" not in sent[2]
    # 全部无异议前不得进入报告审核：审核询问只有一次（重跑确认后）
    reviews = [e for e in ws.events if e["type"] == "report_review_request"]
    assert len(reviews) == 1


async def test_replay_waits_for_inflight_chat(monkeypatch):
    started = []
    chat_gate = asyncio.Event()

    async def blocking_chat(agent, message):
        await chat_gate.wait()

    async def fake_stream(msg, **kwargs):
        started.append("diagnosis started")
        yield {"event_type": "start", "payload": {}, "session_id": "s1"}

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    monkeypatch.setattr(mgr, "handle_chat", blocking_chat)
    ws = FakeWS()
    await mgr.connect(ws)

    await mgr.handle_message({"type": "chat", "agent": "commander", "message": "排除鸟害工具"})
    await mgr.handle_message({"type": "replay"})
    await asyncio.sleep(0.1)
    # chat 干预仍在进行，诊断流不得启动
    assert "diagnosis started" not in started
    chat_gate.set()
    await mgr.current_task
    assert "diagnosis started" in started


async def test_realtime_no_confirm(monkeypatch):
    sent = []
    mgr = make_mgr(monkeypatch, sent)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.run_diagnosis(replay=False)
    assert not [e for e in ws.events if e["type"] == "tool_confirm_request"]


async def test_replay_error_clears_confirm_queue(monkeypatch):
    sent = []

    async def failing_stream(msg):
        sent.append(msg)
        yield {"event_type": "start", "payload": {}, "session_id": "s1"}
        # 先广播一个工具结果（复盘模式下会进入 pending_confirms）
        yield {"event_type": "result", "payload": {
            "tool": "LightningDiagnosisTool",
            "output": {"structured_data": {"fault_type": "雷击-绕击", "confidence": 0.985,
                                           "evidence": ["证据A"]}, "raw_text": "raw"}},
         "session_id": "s1"}
        # 随后 PLD 报错
        yield {"event_type": "error", "payload": {"message": "PLD 崩溃"}, "session_id": "s1"}

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", failing_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)

    await mgr.run_diagnosis(replay=True)
    assert mgr.pending_confirms == {}
    assert mgr.confirm_decisions == {}
    assert any(e["type"] == "confirm_queue_clear" for e in ws.events)
    # 确认请求曾广播过，随后被清空事件覆盖
    assert any(e["type"] == "tool_confirm_request" for e in ws.events)


async def test_report_review_loop(monkeypatch):
    sent = []
    mgr = make_mgr(monkeypatch, sent)
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.3)
        # 先确认工具结果(无异议),否则 run 不会进入报告审核循环
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool",
                                  "decision": "ok"})
        await asyncio.sleep(0.3)
        # 第一轮:不满意,要求删第三章
        await mgr.handle_message({"type": "report_review_response",
                                  "satisfied": False, "instruction": "删除第三章"})
        await asyncio.sleep(0.3)
        # 第二轮:满意
        await mgr.handle_message({"type": "report_review_response",
                                  "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    reviews = [e for e in ws.events if e["type"] == "report_review_request"]
    assert len(reviews) == 2
    assert any("删除第三章" in m for m in sent[1:])  # sent[0] 是诊断消息本身
