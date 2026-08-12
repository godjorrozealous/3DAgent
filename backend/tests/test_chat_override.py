"""复盘对话异议升格为数据修正(override):用户新数据生效通道。"""
import agent_manager
from tests.test_agent_manager import FakeWS

SESSION = {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}


def make_mgr(monkeypatch):
    async def fake_stream(msg, **kwargs):
        yield {"event_type": "complete", "payload": {}, "session_id": "s1"}

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    mgr._run_replay = True
    return mgr


async def test_chat_objection_registers_override(monkeypatch):
    """对话异议登记时同步写 value_overrides(用户陈述即权威数据)。"""
    mgr = make_mgr(monkeypatch)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind",
                              "message": "数据修正:风速15m/s,绝缘子串风偏角10度"})
    assert mgr.value_overrides["WindDiagnosisTool"] == "数据修正:风速15m/s,绝缘子串风偏角10度"
    assert mgr.confirm_decisions["WindDiagnosisTool"]["decision"] == "chat"


async def test_second_chat_objection_overwrites_first(monkeypatch):
    """同一工具多次对话异议:后者覆盖前者。"""
    mgr = make_mgr(monkeypatch)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "数据修正:风速15m/s"})
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "数据修正:风速12m/s"})
    assert mgr.value_overrides["WindDiagnosisTool"] == "数据修正:风速12m/s"


def test_objection_command_chat_becomes_strong_override():
    """chat 分支:trail kind=chat_override + 强约束 suffix。"""
    mgr = agent_manager.AgentManager()
    kind, text = mgr._objection_command(
        "WindDiagnosisTool", {"decision": "chat", "value": "风速15m/s,风偏角10度"})
    assert kind == "suffix"
    assert "WindDiagnosisTool" in text
    assert "风速15m/s,风偏角10度" in text
    assert "以用户提供数据为准" in text
    assert mgr.intervention_trail[-1]["kind"] == "chat_override"
    assert mgr.value_overrides["WindDiagnosisTool"] == "风速15m/s,风偏角10度"


def test_chat_override_has_label():
    """chat_override 必须进保存清单(_ITEM_LABELS 覆盖,否则干预丢失)。"""
    mgr = agent_manager.AgentManager()
    mgr._trail("chat_override", "WindDiagnosisTool", "风速15m/s")
    items = mgr._intervention_items()
    assert len(items) == 1
    assert items[0]["kind"] == "chat_override"
    assert "数据修正" in items[0]["label"]


async def test_save_strategy_treats_chat_override_as_override(monkeypatch):
    """save_strategy:chat_override 视同 override 进 custom_data 与 trail。"""
    captured = {}

    def fake_build(payload):
        captured.update(payload)
        return "md"

    async def fake_save(name, content):
        return {"success": True}

    monkeypatch.setattr(agent_manager.strategy_builder, "build_skill_markdown", fake_build)
    monkeypatch.setattr(agent_manager.pld_client, "save_skill", fake_save)
    monkeypatch.setattr(agent_manager, "_load_trails", lambda: {})
    monkeypatch.setattr(agent_manager, "_write_trails", lambda t: None)
    mgr = agent_manager.AgentManager()
    mgr._trail("chat_override", "WindDiagnosisTool", "风速15m/s")
    await mgr.save_strategy("测试策略")
    assert any("数据修正" in s for s in captured["custom_data"])
    assert {"kind": "chat_override", "tool": "WindDiagnosisTool", "value": "风速15m/s"} in captured["trail"]
