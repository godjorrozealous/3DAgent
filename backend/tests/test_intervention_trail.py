import agent_manager
from tests.test_agent_manager import FakeWS

SESSION = {"status": "modifying", "active_weights": {}, "excluded_tools": [],
           "action_log": [{"action_type": "exclude", "tool_name": "BirdDamageDiagnosisTool"},
                          {"action_type": "exclude", "tool_name": "X"}]}

async def test_report_summary_action_log_is_delta(monkeypatch):
    async def fake_stream(msg):
        yield {"event_type": "complete", "payload": {"report": "r", "summary": {}}, "session_id": "s1"}
    async def fake_session(sid):
        return SESSION
    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    mgr._action_count_at_start = 1  # 本轮开始前已有 1 条历史
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.run_diagnosis(replay=False)
    summary_events = [e for e in ws.events if e.get("type") == "report_summary"]
    assert len(summary_events[0]["action_log"]) == 1  # 只有本轮新增的 1 条
