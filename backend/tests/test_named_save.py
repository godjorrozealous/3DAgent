import json
import agent_manager
from tests.test_agent_manager import FakeWS

async def test_named_save_with_dedupe_and_trail(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_manager, "TRAILS_FILE", tmp_path / "trails.json")
    saved = {}
    async def fake_skill(name, content):
        saved["name"] = name
        return {"success": True}
    async def fake_session(sid):
        return {"active_weights": {"LightningDiagnosisTool": 1.0}, "excluded_tools": ["BirdDamageDiagnosisTool"]}
    monkeypatch.setattr(agent_manager.pld_client, "save_skill", fake_skill)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    mgr.saved_strategies = [{"name": "夏季策略"}]
    mgr.intervention_trail = [{"kind": "exclude", "tool": "BirdDamageDiagnosisTool", "value": None, "text": "", "time": "10:00:00"}]
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.save_strategy("夏季策略")
    assert saved["name"] == "夏季策略_2"  # 重名追加序号
    trails = json.loads((tmp_path / "trails.json").read_text())
    assert trails["夏季策略_2"][0]["kind"] == "exclude"


async def test_named_save_space_to_underscore(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_manager, "TRAILS_FILE", tmp_path / "trails.json")
    saved = {}
    async def fake_skill(name, content):
        saved["name"] = name
        return {"success": True}
    async def fake_session(sid):
        return {"active_weights": {}, "excluded_tools": []}
    monkeypatch.setattr(agent_manager.pld_client, "save_skill", fake_skill)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    mgr.intervention_trail = []
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.save_strategy("夏季 策略")
    assert saved["name"] == "夏季_策略"  # 空格转下划线，中文保留
