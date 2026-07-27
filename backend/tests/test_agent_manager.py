import json
import pytest
import agent_manager


class FakeWS:
    def __init__(self):
        self.events = []

    async def send_json(self, e):
        self.events.append(e)

    # WebSocket 协议兼容
    async def accept(self):
        pass


def make_manager(monkeypatch, stream_events, session):
    async def fake_stream(msg):
        for e in stream_events:
            yield e

    async def fake_session(sid):
        return session

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    return mgr


COMPLETE_STREAM = [
    {"event_type": "start", "payload": {}, "session_id": "s1"},
    {"event_type": "complete", "payload": {
        "report": "# 报告", "summary": {"fault_type": "雷击-绕击", "confidence": 0.98}},
     "session_id": "s1"},
]

SESSION = {"status": "modifying", "active_weights": {"LightningDiagnosisTool": 1.0},
           "excluded_tools": [], "action_log": []}


async def test_report_summary_event(monkeypatch):
    mgr = make_manager(monkeypatch, COMPLETE_STREAM, SESSION)
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.run_diagnosis(replay=False)
    rs = [e for e in ws.events if e["type"] == "report_summary"]
    assert len(rs) == 1
    assert rs[0]["kind"] == "realtime"
    assert rs[0]["summary"]["fault_type"] == "雷击-绕击"
    assert rs[0]["report"] == "# 报告"
    assert "action_log" in rs[0] and "weights" in rs[0]
    assert mgr.last_summaries["realtime"]["summary"]["confidence"] == 0.98


async def test_report_summary_replay_kind(monkeypatch):
    mgr = make_manager(monkeypatch, COMPLETE_STREAM, SESSION)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.run_diagnosis(replay=True)
    rs = [e for e in ws.events if e["type"] == "report_summary"]
    assert rs[0]["kind"] == "replay"


SESSION_WITH_ACTIONS = {"status": "modifying", "active_weights": {},
                        "excluded_tools": ["BirdDamageDiagnosisTool"],
                        "action_log": [{"action_type": "exclude", "parameters": {}}]}


async def test_prompt_save_strategy_on_intervention(monkeypatch):
    mgr = make_manager(monkeypatch, COMPLETE_STREAM, SESSION_WITH_ACTIONS)
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.run_diagnosis(replay=False)
    prompts = [e for e in ws.events if e["type"] == "prompt_save_strategy"]
    assert len(prompts) == 1
    assert prompts[0]["interventions"] >= 1
    assert prompts[0]["context"] == "realtime"


async def test_no_prompt_without_intervention(monkeypatch):
    mgr = make_manager(monkeypatch, COMPLETE_STREAM, SESSION)
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.run_diagnosis(replay=False)
    assert not [e for e in ws.events if e["type"] == "prompt_save_strategy"]
