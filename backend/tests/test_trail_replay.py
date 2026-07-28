import json
import agent_manager
from tests.test_agent_manager import FakeWS

async def test_activate_replays_trail(monkeypatch, tmp_path):
    trails_file = tmp_path / "trails.json"
    trails_file.write_text(json.dumps({"夏季策略": [
        {"kind": "override", "tool": "LightningDiagnosisTool", "value": "雷电流 28kA", "text": "", "time": "t"},
        {"kind": "report_modify", "tool": "", "value": None, "text": "删除第三章", "time": "t"},
        {"kind": "exclude", "tool": "BirdDamageDiagnosisTool", "value": None, "text": "", "time": "t"},
    ]}, ensure_ascii=False))
    monkeypatch.setattr(agent_manager, "TRAILS_FILE", trails_file)
    sent = []
    async def fake_default(name):
        return {"success": True}
    async def fake_stream(msg):
        sent.append(msg)
        yield {"event_type": "complete", "payload": {"report": "new", "summary": {}}, "session_id": "s1"}
    async def fake_session(sid):
        return {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}
    monkeypatch.setattr(agent_manager.pld_client, "set_default_skill", fake_default)
    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "activate_skill", "name": "夏季策略"})
    assert mgr.value_overrides["LightningDiagnosisTool"] == "雷电流 28kA"
    assert any("删除第三章" in m for m in sent)  # report_modify 重放
    assert not any("排除" in m for m in sent)    # exclude 由 PLD 技能承载,不重放
