"""复盘权重干预：重跑生效，复盘结束后自动还原为调整前数值。

权重修改只应保存在用户保存的策略中（激活时才生效），不得固化到 PLD 会话当前权重。
"""
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
# 会话当前权重：雷电 1.0（调整前）
SESSION = {"status": "modifying",
           "active_weights": {"LightningDiagnosisTool": 1.0, "WindDiagnosisTool": 0.8},
           "excluded_tools": [], "action_log": []}


def make_mgr(monkeypatch, calls, streams, session=SESSION):
    iters = [iter(s) for s in streams]

    async def fake_stream(msg, **kwargs):
        calls.append(msg)
        for e in iters.pop(0):
            yield e

    async def fake_session(sid):
        return session

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    return mgr


async def test_weight_restored_after_replay(monkeypatch):
    """权重异议：0.1 先落地让重跑生效；复盘结束后自动恢复为调整前的 1.0。"""
    calls = []
    streams = [
        # 流1=首轮诊断(defer), 流2=weight命令(0.1), 流3=裸诊断重跑(defer),
        # 流4=无异议终轮(生成报告), 流5=恢复命令(1.0)
        [{"event_type": "start", "payload": {}, "session_id": "s1"}, RESULT_OK, COMPLETE],
        [{"event_type": "complete", "payload": {"message": "ok"}, "session_id": "s1"}],
        [{"event_type": "start", "payload": {}, "session_id": "s1"}, RESULT_OK, COMPLETE],
        [{"event_type": "start", "payload": {}, "session_id": "s1"}, RESULT_OK, COMPLETE],
        [{"event_type": "complete", "payload": {"message": "ok"}, "session_id": "s1"}],
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
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.3)
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    assert calls[1] == "将LightningDiagnosisTool权重调整为0.1"
    assert calls[2] == calls[0]
    assert calls[3] == calls[0]  # 无异议终轮:裸诊断消息生成报告
    # 复盘结束后自动还原为调整前数值
    assert calls[4] == "将LightningDiagnosisTool权重调整为1.0"
    assert any("权重" in e.get("message", "") and "恢复" in e.get("message", "")
               for e in ws.events if e["type"] == "log")
    # 还原后刷新 HUD 快照：权重回到 1.0
    snaps = [e for e in ws.events if e["type"] == "session_snapshot"]
    assert snaps and snaps[-1]["weights"].get("LightningDiagnosisTool") == 1.0


async def test_no_restore_without_weight_objection(monkeypatch):
    """无权重异议的复盘：不得下发任何恢复命令。"""
    calls = []
    streams = [
        [{"event_type": "start", "payload": {}, "session_id": "s1"}, RESULT_OK, COMPLETE],
        # 无异议终轮(生成报告)
        [{"event_type": "start", "payload": {}, "session_id": "s1"}, RESULT_OK, COMPLETE],
    ]
    mgr = make_mgr(monkeypatch, calls, streams)
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.3)
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.3)
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    assert len(calls) == 2  # 首轮诊断(defer) + 无异议终轮
    assert not any("权重调整" in c for c in calls)  # 无权重相关命令
