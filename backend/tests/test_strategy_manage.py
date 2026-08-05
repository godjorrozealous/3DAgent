"""策略管理：列表来自 PLD 技能；删除逐条调 PLD DELETE，使用中默认策略跳过。"""
import agent_manager
from tests.test_agent_manager import FakeWS


def make_mgr(monkeypatch):
    deleted = []

    async def fake_list():
        return {"skills": [
            {"name": "策略A", "description": "d", "is_default": False, "source": "用户自定义"},
            {"name": "策略B", "description": "d", "is_default": False, "source": "用户自定义"},
        ]}

    async def fake_default():
        return {"default_skill": "策略B"}

    async def fake_delete(name):
        deleted.append(name)
        return {"success": True}

    monkeypatch.setattr(agent_manager.pld_client, "list_skills", fake_list)
    monkeypatch.setattr(agent_manager.pld_client, "get_default_skill", fake_default)
    monkeypatch.setattr(agent_manager.pld_client, "delete_skill", fake_delete)
    return agent_manager.AgentManager(), deleted


async def test_list_strategies_broadcast(monkeypatch):
    mgr, _ = make_mgr(monkeypatch)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "list_strategies"})
    ev = [e for e in ws.events if e["type"] == "strategies_list"][-1]
    assert [s["name"] for s in ev["strategies"]] == ["策略A", "策略B"]
    assert ev["default"] == "策略B"


async def test_delete_skips_default_and_broadcasts(monkeypatch):
    mgr, deleted = make_mgr(monkeypatch)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "delete_strategies", "names": ["策略A", "策略B"]})
    assert deleted == ["策略A"]          # 使用中的默认策略跳过
    assert any(e["type"] == "strategies_list" for e in ws.events)
    logs = [e["message"] for e in ws.events if e["type"] == "log"]
    assert any("策略B" in m and "跳过" in m or "删除失败" in m for m in logs)
