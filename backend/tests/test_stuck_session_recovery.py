"""PLD 会话卡死（diagnosing 残留）自动恢复回归。"""
import agent_manager
from tests.test_agent_manager import FakeWS

ERROR_STREAM = [
    {"event_type": "start", "payload": {}, "session_id": "s1"},
    {"event_type": "error", "payload": {"message": "当前状态 diagnosing 不允许执行诊断"},
     "session_id": "s1"},
]
OK_STREAM = [
    {"event_type": "start", "payload": {}, "session_id": "s1"},
    {"event_type": "complete", "payload": {
        "report": "# 报告", "summary": {"fault_type": "雷击", "confidence": 0.9}},
     "session_id": "s1"},
]
SESSION = {"status": "modifying", "active_weights": {"LightningDiagnosisTool": 1.0},
           "excluded_tools": [], "action_log": []}


async def test_stuck_pld_session_auto_reset_and_retry(monkeypatch):
    """首发被 PLD 以「状态 diagnosing」拒绝时，自动 reset 会话并重试成功。"""
    streams = [iter(ERROR_STREAM), iter(OK_STREAM)]
    resets = []

    async def fake_stream(msg):
        for e in streams.pop(0):
            yield e

    async def fake_reset(sid):
        resets.append(sid)
        return {"success": True}

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "reset_session", fake_reset)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)

    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.run_diagnosis(replay=False, text="雅湖线 2025-05-08 跳闸")

    assert resets == ["s1"]                     # 复位过一次
    assert not streams                          # 两条流都消费了（失败+重试）
    assert mgr.status["commander"] != "error"   # 未落入错误态


async def test_other_pld_errors_do_not_retry(monkeypatch):
    """非卡死类错误不重试、不复位，直接落入错误态。"""
    resets = []

    async def fake_stream(msg):
        for e in ERROR_STREAM[:1]:
            yield e
        yield {"event_type": "error", "payload": {"message": "LLM 服务不可用"},
               "session_id": "s1"}

    async def fake_reset(sid):
        resets.append(sid)
        return {"success": True}

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "reset_session", fake_reset)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)

    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.run_diagnosis(replay=False, text="雅湖线 2025-05-08 跳闸")

    assert resets == []
    assert mgr.status["commander"] == "error"
