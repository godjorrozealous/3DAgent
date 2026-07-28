import agent_manager
from tests.test_agent_manager import FakeWS


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
        {"event_type": "thinking", "payload": {"message": "诊断计划: 调用 LightningDiagnosisTool, WindDiagnosisTool"}, "session_id": "s1"},
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
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.run_diagnosis(replay=False)
    # 计划经事件流注入(与生产一致),而非直接预设 planned_tools
    assert mgr.planned_tools == ["LightningDiagnosisTool", "WindDiagnosisTool"]
    # 计划内:running;计划外(icing/bird):先 running 后 idle(亮一下就灭)
    lightning_states = [e["status"] for e in ws.events if e.get("type") == "agent_status" and e.get("agent") == "lightning"]
    icing_states = [e["status"] for e in ws.events if e.get("type") == "agent_status" and e.get("agent") == "icing"]
    assert "running" in lightning_states
    assert icing_states[:2] == ["running", "idle"]
    # 证明 icing 走的是 blink 分支:存在「本轮未调用该工具」日志
    blink_logs = [
        e for e in ws.events
        if e.get("type") == "log" and e.get("agent") == "icing" and "本轮未调用该工具" in e.get("message", "")
    ]
    assert blink_logs


async def test_planned_tools_reset_between_runs(monkeypatch):
    """回归:planned_tools 每轮开跑重置——本轮流中无「诊断计划」时应回退为全工具计划。"""
    # 流中不含「诊断计划」thinking;不含 complete,避免 _finish_run 补记日志干扰断言
    stream = [
        {"event_type": "start", "payload": {}, "session_id": "s1"},
        {"event_type": "thinking", "payload": {"message": "执行诊断工具..."}, "session_id": "s1"},
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
    mgr.planned_tools = ["LightningDiagnosisTool"]  # 模拟上一轮残留
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.run_diagnosis(replay=False)
    assert mgr.planned_tools == []
    # 回退为全工具计划:四个工具席位全部 running,且无「本轮未调用该工具」闪烁日志
    for aid in ("lightning", "wind", "icing", "bird"):
        states = [e["status"] for e in ws.events if e.get("type") == "agent_status" and e.get("agent") == aid]
        assert "running" in states, aid
        blink_logs = [
            e for e in ws.events
            if e.get("type") == "log" and e.get("agent") == aid and "本轮未调用该工具" in e.get("message", "")
        ]
        assert not blink_logs, aid
