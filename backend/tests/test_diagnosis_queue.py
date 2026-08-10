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
    async def fake_stream(msg, **kwargs):
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


REPLAY_STREAM = [
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


async def test_replay_end_drains_queue(monkeypatch):
    """回归：复盘运行中入队的实时诊断，复盘结束后应自动开始（此前 finally 跳过排空导致滞留）。"""
    calls = []

    async def fake_stream(msg, **kwargs):
        calls.append(msg)
        for e in REPLAY_STREAM:
            yield e

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)

    await mgr.handle_message({"type": "replay"})
    replay_task = mgr.current_task
    await asyncio.sleep(0.3)  # 复盘进行中（阻塞在工具确认上）

    # 复盘运行中提交新线路 -> 入队而非直接执行
    await mgr.handle_message({"type": "start_diagnosis", "text": "线路B 跳闸"})
    assert len(mgr.diagnosis_queue) == 1
    assert mgr.diagnosis_queue[0]["text"] == "线路B 跳闸"

    async def respond():
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool",
                                  "decision": "ok"})
        await asyncio.sleep(0.3)
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(replay_task, respond())
    await asyncio.sleep(0.5)  # 让 finally 启动的排队任务执行
    assert "线路B 跳闸" in calls  # 复盘结束后自动开始排队线路
    assert mgr.diagnosis_queue == []


async def test_current_line_cleared_after_run(monkeypatch):
    calls = []
    gate = asyncio.Event()
    gate.set()  # 不挂起，直接跑完
    mgr = make_mgr(monkeypatch, calls, gate)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "start_diagnosis", "text": "线路A 跳闸"})
    await asyncio.sleep(0.5)
    assert mgr.current_line == ""
    queues = [e for e in ws.events if e["type"] == "diagnosis_queue"]
    assert queues[-1]["current"] == ""
