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
    mgr.intervention_trail = [{"kind": "exclude", "tool": "BirdDamageDiagnosisTool",
                               "value": None, "text": "", "time": "t"}]
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.save_strategy("夏季 策略")
    assert saved["name"] == "夏季_策略"  # 空格转下划线，中文保留


async def test_save_strategy_builds_full_skill(monkeypatch, tmp_path):
    """保存策略生成完整自包含 skill：含 frontmatter/基线正文/个性化章节。"""
    monkeypatch.setattr(agent_manager, "TRAILS_FILE", tmp_path / "trails.json")
    saved = {}

    async def fake_skill(name, content):
        saved["content"] = content
        return {"success": True}

    async def fake_session(sid):
        return {"active_weights": {"LightningDiagnosisTool": 1.0},
                "excluded_tools": ["BirdDamageDiagnosisTool"]}

    monkeypatch.setattr(agent_manager.pld_client, "save_skill", fake_skill)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    mgr.current_line = "500kV雅湖线 跳闸"
    # 新行为：排除/参数修改/报告修改均来自本轮干预清单（trail），不再拉 session 快照
    mgr.intervention_trail = [
        {"kind": "exclude", "tool": "BirdDamageDiagnosisTool", "value": None, "text": "", "time": "t"},
        {"kind": "override", "tool": "LightningDiagnosisTool",
         "value": "雷电流 28kA", "text": "", "time": "t"},
        {"kind": "report_modify", "tool": "", "value": None, "text": "删除第三章", "time": "t"},
    ]
    mgr.objection_log = [
        {"kind": "diagnosis_objection", "text": "雷电诊断要考虑地形"},
    ]
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.save_strategy("全量策略")
    content = saved["content"]
    assert content.startswith("---\nname: 全量策略")
    assert "输电线路综合诊断" in content          # 基线正文
    assert "SKIP BirdDamageDiagnosisTool entirely" in content
    assert "## 司令决策规则（必须遵循）" in content and "雷电诊断要考虑地形" in content
    assert "## 报告撰写规则（必须遵循）" in content and "删除第三章" in content
    assert "## 用户自定义数据记录" in content


async def test_objection_log_records_confirm_and_chat(monkeypatch, tmp_path):
    """复盘确认异议与用户直聊均写入 objection_log。"""
    monkeypatch.setattr(agent_manager, "TRAILS_FILE", tmp_path / "t.json")
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"

    async def fake_stream(msg, **kwargs):
        yield {"event_type": "complete", "payload": {"report": "r", "summary": {}}, "session_id": "s1"}

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    ws = FakeWS()
    await mgr.connect(ws)
    mgr.pending_confirms["LightningDiagnosisTool"] = {"tool": "LightningDiagnosisTool"}
    mgr._confirms_done = __import__("asyncio").Event()
    await mgr.handle_message({"type": "tool_confirm_response",
                              "tool": "LightningDiagnosisTool",
                              "decision": "override", "value": "雷电流 28kA"})
    assert mgr.objection_log[0]["kind"] == "custom_data"
    await mgr.handle_message({"type": "chat", "agent": "commander", "message": "排除鸟害工具"})
    kinds = [o["kind"] for o in mgr.objection_log]
    assert "user_input" in kinds
