"""activate_skill 路由:激活后双广播(skills + strategies_list)+ 快照刷新。"""
import agent_manager
from tests.test_agent_manager import FakeWS


async def areturn(v):
    return v


async def test_activate_skill_broadcasts_all(monkeypatch):
    """激活后:skills、strategies_list、session_snapshot 三事件齐发(三处 UI 联动)。"""
    monkeypatch.setattr(agent_manager.pld_client, "set_default_skill",
                        lambda name: areturn({"success": True}))
    monkeypatch.setattr(agent_manager.pld_client, "list_skills",
                        lambda: areturn({"skills": [{"name": "s1"}]}))
    monkeypatch.setattr(agent_manager.pld_client, "get_default_skill",
                        lambda: areturn({"default_skill": "s1"}))
    monkeypatch.setattr(agent_manager.pld_client, "get_session",
                        lambda sid: areturn({"active_weights": {"WindDiagnosisTool": 0.5},
                                             "excluded_tools": []}))
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.handle_message({"type": "activate_skill", "name": "s1"})
    types = [e["type"] for e in ws.events]
    assert "skills" in types
    assert "strategies_list" in types
    assert "session_snapshot" in types
    snap = [e for e in ws.events if e["type"] == "session_snapshot"][0]
    assert snap["weights"] == {"WindDiagnosisTool": 0.5}
    assert mgr.local_interventions == 1
