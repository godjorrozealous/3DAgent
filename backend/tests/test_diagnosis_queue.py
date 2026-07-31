"""诊断排队：运行中提交新线路入队，当前完成后自动开始下一个；可取消排队。"""
import asyncio
import agent_manager
from tests.test_agent_manager import FakeWS

COMPLETE_STREAM = [
    {"event_type": "start", "payload": {}, "session_id": "s1"},
    {"event_type": "complete", "payload": {
        "report": "# 报告", "summary": {"fault_type": "雷击", "confidence": 0.9}},
     "session_id": "s1"},
]
SESSION = {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}


def make_mgr(monkeypatch, calls, gate):
    async def fake_stream(msg):
        calls.append(msg)
        if len(calls) == 1:
            await gate.wait()  # 第一轮诊断挂起，模拟执行中
        for e in COMPLETE_STREAM:
            yield e

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    return mgr


async def test_queue_and_auto_start(monkeypatch):
    calls = []
    gate = asyncio.Event()
    mgr = make_mgr(monkeypatch, calls, gate)
    ws = FakeWS()
    await mgr.connect(ws)

    await mgr.handle_message({"type": "start_diagnosis", "text": "线路A 跳闸"})
    await asyncio.sleep(0.1)
    await mgr.handle_message({"type": "start_diagnosis", "text": "线路B 跳闸"})
    assert len(mgr.diagnosis_queue) == 1
    assert mgr.diagnosis_queue[0]["text"] == "线路B 跳闸"
    queues = [e for e in ws.events if e["type"] == "diagnosis_queue"]
    assert queues[-1]["queue"][0]["text"] == "线路B 跳闸"

    gate.set()  # 第一轮放行
    await asyncio.sleep(0.5)
    assert calls[0] == "线路A 跳闸"
    assert "线路B 跳闸" in calls  # 自动开始下一线路
    assert mgr.diagnosis_queue == []


async def test_cancel_queued(monkeypatch):
    calls = []
    gate = asyncio.Event()
    mgr = make_mgr(monkeypatch, calls, gate)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "start_diagnosis", "text": "线路A 跳闸"})
    await asyncio.sleep(0.1)
    await mgr.handle_message({"type": "start_diagnosis", "text": "线路B 跳闸"})
    await mgr.handle_message({"type": "cancel_queued", "index": 0})
    assert mgr.diagnosis_queue == []
    gate.set()
    await asyncio.sleep(0.5)
    assert "线路B 跳闸" not in calls
