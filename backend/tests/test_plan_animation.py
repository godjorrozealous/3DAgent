import asyncio
import agent_manager
from tests.test_agent_manager import FakeWS, make_manager


def test_parse_planned_tools():
    text = "诊断计划: 调用 LightningDiagnosisTool, WindDiagnosisTool | 报告结构: 概述"
    assert agent_manager.parse_planned_tools(text) == ["LightningDiagnosisTool", "WindDiagnosisTool"]
    assert agent_manager.parse_planned_tools("无工具信息") == []
    # 去重保序
    t2 = "调用 BirdDamageDiagnosisTool, LightningDiagnosisTool、BirdDamageDiagnosisTool"
    assert agent_manager.parse_planned_tools(t2) == ["BirdDamageDiagnosisTool", "LightningDiagnosisTool"]


async def test_skipped_agents_blink_and_planned_run(monkeypatch):
    stream = [
        {"event_type": "start", "payload": {}, "session_id": "s1"},
        {"event_type": "thinking", "payload": {"message": "执行诊断工具..."}, "session_id": "s1"},
        {"event_type": "complete", "payload": {"report": "r", "summary": {}}, "session_id": "s1"},
    ]
    monkeypatch.setattr(agent_manager, "DIAGNOSE_MESSAGE", "x")
    async def fake_stream(msg):
        for e in stream:
            yield e
    async def fake_session(sid):
        return {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}
    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.planned_tools = ["LightningDiagnosisTool", "WindDiagnosisTool"]
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.run_diagnosis(replay=False)
    # 计划内:running;计划外(icing/bird):先 running 后 idle(亮一下就灭)
    lightning_states = [e["status"] for e in ws.events if e.get("type") == "agent_status" and e.get("agent") == "lightning"]
    icing_states = [e["status"] for e in ws.events if e.get("type") == "agent_status" and e.get("agent") == "icing"]
    assert "running" in lightning_states
    assert icing_states[:2] == ["running", "idle"]
