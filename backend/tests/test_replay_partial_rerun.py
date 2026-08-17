"""复盘局部重跑：①命令带 defer、②收尾带 session_id、还原带 defer。"""
import asyncio

import agent_manager
from tests.test_agent_manager import FakeWS

RESULT_OK = {"event_type": "result", "session_id": "s1",
             "payload": {"tool": "LightningDiagnosisTool",
                         "output": {"fault_type": "雷击", "confidence": 0.9,
                                    "evidence": "e", "raw_text": "r", "structured_data": {}}}}
COMPLETE = {"event_type": "complete", "session_id": "s1",
            "payload": {"report": "报告正文", "summary": {"fault_type": "雷击", "confidence": 0.9}}}
SESSION = {"status": "modifying",
           "active_weights": {"LightningDiagnosisTool": 1.0},
           "excluded_tools": [], "action_log": []}


def make_mgr(monkeypatch, calls, streams):
    iters = [iter(s) for s in streams]

    async def fake_stream(msg, **kwargs):
        calls.append((msg, kwargs))
        for e in iters.pop(0):
            yield e

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    return mgr


async def test_objection_cmds_defer_rerun_session_id_restore_defer(monkeypatch):
    """权重异议复盘全流程：校验各类 chat_stream 调用的编排参数。"""
    calls = []
    streams = [
        [dict(RESULT_OK), dict(COMPLETE)],   # 首轮诊断(defer 确认轮)
        [dict(RESULT_OK), dict(COMPLETE)],   # ①命令(auto-chain已被defer,直接complete)
        [dict(RESULT_OK), dict(COMPLETE)],   # ②重跑(defer 确认轮)
        [dict(RESULT_OK), dict(COMPLETE)],   # ③无异议终轮(生成报告)
        [dict(COMPLETE)],                    # 还原指令
    ]
    mgr = make_mgr(monkeypatch, calls, streams)
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.3)
        # 首轮逐项确认：权重异议（结构化命令路径）
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool",
                                  "decision": "weight", "value": 0.1})
        await asyncio.sleep(0.6)
        # 重跑轮逐项确认：无异议
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.3)
        # 终轮报告审核：满意结束
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())

    assert len(calls) == 5
    first, cmd, rerun, final, restore = calls
    # 首轮：defer_report 确认轮(只跑工具不出报告)
    assert first[1] == {"defer_report": True}
    # ①结构化命令：defer_rediagnose
    assert "权重调整为0.1" in cmd[0]
    assert cmd[1].get("defer_rediagnose") is True
    # ②重跑：session_id 续跑 + defer_report 确认轮
    assert rerun[1].get("session_id") == "s1"
    assert rerun[1].get("defer_report") is True
    # ③无异议终轮：session_id 续跑,不带 defer_report(生成报告)
    assert final[1].get("session_id") == "s1"
    assert "defer_report" not in final[1]
    # 还原指令：defer_rediagnose
    assert "权重调整为1.0" in restore[0]
    assert restore[1].get("defer_rediagnose") is True
