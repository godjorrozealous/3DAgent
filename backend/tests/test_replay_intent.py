"""复盘对话异议 LLM 意图映射:classify → 结构化决策/数据修正/报告修改/固定提示。"""
import agent_manager
from tests.test_agent_manager import FakeWS


def make_mgr(monkeypatch, classify_resp=None, classify_exc=None):
    async def fake_classify(message, session_id=None):
        if classify_exc:
            raise classify_exc
        return classify_resp or {"intent_type": "general", "confidence": 1.0,
                                 "parameters": {}}

    monkeypatch.setattr(agent_manager.pld_client, "classify", fake_classify)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    mgr._run_replay = True
    return mgr


async def test_adjust_weight_maps_to_weight_decision(monkeypatch):
    """「调整权重0.1」→ adjust_weight → weight 决策;不写 value_overrides。"""
    mgr = make_mgr(monkeypatch, {
        "intent_type": "adjust_weight", "confidence": 0.95,
        "parameters": {"tool_name": "LightningDiagnosisTool", "weight": 0.1}})
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "lightning",
                              "message": "调整权重0.1"})
    assert mgr.confirm_decisions["LightningDiagnosisTool"] == {
        "decision": "weight", "value": 0.1}
    assert mgr.value_overrides == {}


async def test_adjust_weight_without_value_falls_back_to_data_fix(monkeypatch):
    """adjust_weight 未提取到权重值 → 按数据修正兜底。"""
    mgr = make_mgr(monkeypatch, {
        "intent_type": "adjust_weight", "confidence": 0.8, "parameters": {}})
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "调整权重"})
    assert mgr.confirm_decisions["WindDiagnosisTool"]["decision"] == "chat"
    assert mgr.value_overrides["WindDiagnosisTool"] == "调整权重"


async def test_general_maps_to_data_fix(monkeypatch):
    """「风速10m/s」(general)→ 数据修正,无需关键词。"""
    mgr = make_mgr(monkeypatch)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "风速10m/s"})
    assert mgr.confirm_decisions["WindDiagnosisTool"]["decision"] == "chat"
    assert mgr.value_overrides["WindDiagnosisTool"] == "风速10m/s"


async def test_recheck_and_exclude_mapping(monkeypatch):
    """recheck_tool / exclude_tool → 对应结构化决策;tool 取 parameters.tool_name。"""
    mgr = make_mgr(monkeypatch, {
        "intent_type": "recheck_tool", "confidence": 0.9,
        "parameters": {"tool_name": "LightningDiagnosisTool"}})
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "重新检查雷电"})
    assert mgr.confirm_decisions["LightningDiagnosisTool"]["decision"] == "recheck"

    mgr2 = make_mgr(monkeypatch, {
        "intent_type": "exclude_tool", "confidence": 0.9,
        "parameters": {"tool_name": "IcingDiagnosisTool"}})
    await mgr2.connect(FakeWS())
    await mgr2.handle_message({"type": "chat", "agent": "wind", "message": "排除覆冰"})
    assert mgr2.confirm_decisions["IcingDiagnosisTool"]["decision"] == "exclude"


async def test_modify_report_maps_to_report_modify(monkeypatch):
    """「去掉第六章」→ modify_report → report_modify 决策(trail 复用既有 kind)。"""
    mgr = make_mgr(monkeypatch, {
        "intent_type": "modify_report", "confidence": 0.9, "parameters": {}})
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "去掉第六章"})
    assert mgr.confirm_decisions["WindDiagnosisTool"] == {
        "decision": "report_modify", "value": "去掉第六章"}
    assert mgr.value_overrides == {}
    kind, text = mgr._objection_command(
        "WindDiagnosisTool", {"decision": "report_modify", "value": "去掉第六章"})
    assert kind == "suffix"
    assert "修改报告" in text and "去掉第六章" in text
    assert mgr.intervention_trail[-1]["kind"] == "report_modify"


async def test_unsupported_intent_fixed_hint(monkeypatch):
    """include_tool/complete 等 → 固定提示,不登记决策。"""
    mgr = make_mgr(monkeypatch, {
        "intent_type": "include_tool", "confidence": 0.9,
        "parameters": {"tool_name": "IcingDiagnosisTool"}})
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "恢复覆冰"})
    assert mgr.confirm_decisions == {}
    assert mgr.value_overrides == {}
    assert any("界面按钮" in e.get("message", "") for e in ws.events
               if e.get("type") == "chat")


async def test_classify_failure_falls_back_to_data_fix(monkeypatch):
    """classify 异常(PLD 不可达)→ 数据修正兜底,链路不中断。"""
    mgr = make_mgr(monkeypatch, classify_exc=ConnectionError("down"))
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "风速10m/s"})
    assert mgr.confirm_decisions["WindDiagnosisTool"]["decision"] == "chat"
    assert mgr.value_overrides["WindDiagnosisTool"] == "风速10m/s"


async def test_unknown_tool_name_falls_back_to_chat_agent(monkeypatch):
    """parameters.tool_name 非标准工具名 → 用对话所在智能体工具。"""
    mgr = make_mgr(monkeypatch, {
        "intent_type": "recheck_tool", "confidence": 0.9,
        "parameters": {"tool_name": "雷电工具"}})
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "重新检查"})
    assert mgr.confirm_decisions["WindDiagnosisTool"]["decision"] == "recheck"
