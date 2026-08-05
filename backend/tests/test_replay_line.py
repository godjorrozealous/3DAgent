"""自由文本线路 × 复盘 × 策略保存 主链路回归（最终审查 C1/I1）。"""
import asyncio
import agent_manager
from tests.test_agent_manager import FakeWS

COMPLETE_STREAM = [
    {"event_type": "start", "payload": {}, "session_id": "s1"},
    {"event_type": "complete", "payload": {
        "report": "# 报告", "summary": {"fault_type": "雷击", "confidence": 0.9}},
     "session_id": "s1"},
]
SESSION = {"status": "modifying", "active_weights": {"LightningDiagnosisTool": 1.0},
           "excluded_tools": [], "action_log": []}


def make_mgr(monkeypatch, calls):
    async def fake_stream(msg):
        calls.append(msg)
        for e in COMPLETE_STREAM:
            yield e

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    return mgr


async def test_replay_uses_last_realtime_line(monkeypatch):
    """实时诊断线路B后复盘，下发 PLD 的消息必须仍是线路B而非硬编码雅湖线。"""
    calls = []
    mgr = make_mgr(monkeypatch, calls)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.run_diagnosis(replay=False, text="500kV线路B 跳闸")
    assert calls[0] == "500kV线路B 跳闸"

    async def respond():
        await asyncio.sleep(0.2)
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    assert calls[-1].startswith("500kV线路B 跳闸")
    assert "雅湖线" not in calls[-1]


async def test_save_strategy_uses_last_line_after_run(monkeypatch, tmp_path):
    """诊断结束（current_line 已清空）后保存策略，frontmatter 仍含真实线路名。"""
    monkeypatch.setattr(agent_manager, "TRAILS_FILE", tmp_path / "t.json")
    calls = []
    saved = {}

    async def fake_skill(name, content):
        saved["content"] = content
        return {"success": True}

    mgr = make_mgr(monkeypatch, calls)
    monkeypatch.setattr(agent_manager.pld_client, "save_skill", fake_skill)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.run_diagnosis(replay=False, text="500kV线路B 跳闸")
    assert mgr.current_line == ""  # 结束后已清空
    # 新行为：无干预项不保存；补一条本轮干预后保存
    mgr.intervention_trail = [{"kind": "weight", "tool": "LightningDiagnosisTool",
                               "value": 0.5, "text": "", "time": "t"}]
    await mgr.save_strategy("线路B策略")
    assert "500kV线路B 跳闸" in saved["content"]
    # 兜底串 "transmission lines" 不应出现在 {line} 替换位（模板静态文案本身含该词组）
    assert "faults for transmission lines" not in saved["content"]
