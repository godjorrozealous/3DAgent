"""保存清单去重(auto_merged)+ report_summary 事件补全(overrides/report_modifies)。"""
import agent_manager
from tests.test_agent_manager import COMPLETE_STREAM, SESSION, FakeWS, make_manager


def test_auto_merged_entry_excluded_from_items():
    """①②提报的合并日志条目(auto_merged)不进保存清单,消除「总结」歧义。"""
    mgr = agent_manager.AgentManager()
    mgr._trail("weight", "LightningDiagnosisTool", 0.1)
    mgr._trail("override", "WindDiagnosisTool", "风速15m/s")
    mgr._trail("report_modify", text="去掉第六章")
    mgr.objection_log.append({
        "time": "12:00:00", "kind": "diagnosis_objection",
        "text": "将LightningDiagnosisTool权重调整为0.1；将WindDiagnosisTool相关数值修正为风速15m/s",
        "auto_merged": True})
    items = mgr._intervention_items()
    assert len(items) == 3
    assert not any(it["kind"] == "diagnosis_objection" for it in items)


def test_manual_diagnosis_objection_kept():
    """审核期用户手输的诊断流程异议(无 auto_merged 标记)照常进清单。"""
    mgr = agent_manager.AgentManager()
    mgr.objection_log.append({
        "time": "12:00:00", "kind": "diagnosis_objection", "text": "重新组织取数逻辑"})
    items = mgr._intervention_items()
    assert any(it["kind"] == "diagnosis_objection" and "诊断要求" in it["label"]
               for it in items)


async def test_report_summary_carries_overrides_and_report_modifies(monkeypatch):
    """report_summary 事件携带 overrides 与 report_modifies(前端比对消费)。"""
    mgr = make_manager(monkeypatch, COMPLETE_STREAM, SESSION)
    mgr.value_overrides["WindDiagnosisTool"] = "风速15m/s"
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    # intervention_trail 每轮开跑时重置(run_diagnosis 开头),须在轮内注入,
    # 模拟真实流程中审核期 report_modify 在轮内 _trail(见 test_agent_manager 同构写法)
    orig_stream = agent_manager.pld_client.chat_stream

    async def injecting_stream(msg, **kwargs):
        mgr._trail("report_modify", text="去掉第六章")
        async for e in orig_stream(msg, **kwargs):
            yield e

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", injecting_stream)
    await mgr.run_diagnosis(replay=False)
    rs = [e for e in ws.events if e["type"] == "report_summary"]
    assert len(rs) == 1
    assert rs[0]["overrides"] == {"WindDiagnosisTool": "风速15m/s"}
    assert rs[0]["report_modifies"] == ["去掉第六章"]
