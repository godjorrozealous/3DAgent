"""report_chunk 事件:累积进 report_buf,广播增量 delta(O(n) 流量);complete 全量覆盖。"""
import agent_manager
from tests.test_agent_manager import FakeWS


async def _chunks(events):
    for e in events:
        yield e


async def test_report_chunk_broadcasts_delta(monkeypatch):
    events = [
        {"event_type": "start", "payload": {}, "session_id": "s1"},
        {"event_type": "report_chunk", "payload": {"content": "# 报告"}, "session_id": "s1"},
        {"event_type": "report_chunk", "payload": {"content": "\n章节"}, "session_id": "s1"},
        {"event_type": "complete",
         "payload": {"report": "# 报告\n章节", "summary": {"fault_type": "雷击", "confidence": 0.9}},
         "session_id": "s1"},
    ]
    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", lambda *a, **kw: _chunks(events))
    mgr = agent_manager.AgentManager()
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.run_diagnosis(text="雅湖线测试")
    reports = [e for e in ws.events if e["type"] == "report" and not e.get("reset")]
    inc = [e for e in reports if not e["done"]]
    # 增量广播:每条只带本次 delta,不含全量 content
    assert [e["delta"] for e in inc] == ["# 报告", "\n章节"]
    assert all("content" not in e for e in inc)
    final = [e for e in reports if e["done"]][-1]
    assert final["content"] == "# 报告\n章节"                # complete 全量覆盖
