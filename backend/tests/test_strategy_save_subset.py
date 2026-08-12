"""保存策略子集：勾选部分干预生成 markdown；仅复盘轮触发保存提示。"""
import asyncio

import pytest

import agent_manager
import strategy_builder
from tests.test_agent_manager import FakeWS

SESSION = {"status": "modifying",
           "active_weights": {"LightningDiagnosisTool": 0.1, "WindDiagnosisTool": 0.8},
           "excluded_tools": ["BirdDamageDiagnosisTool"], "action_log": []}


@pytest.fixture(autouse=True)
def _isolate_trails(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_manager, "TRAILS_FILE", tmp_path / "trails.json")


def make_mgr(monkeypatch):
    saved = {}

    async def fake_skill(name, content):
        saved["name"] = name
        saved["content"] = content
        return {"success": True}

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "save_skill", fake_skill)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    mgr.current_line = "雅湖线 跳闸"
    return mgr, saved


def seed_trail(mgr):
    mgr.intervention_trail = [
        {"kind": "weight", "tool": "LightningDiagnosisTool", "value": 0.1, "text": "", "time": "t"},
        {"kind": "exclude", "tool": "BirdDamageDiagnosisTool", "value": None, "text": "", "time": "t"},
        {"kind": "report_modify", "tool": "", "value": None, "text": "增加标题", "time": "t"},
    ]


async def test_save_subset_only_selected_items(monkeypatch):
    mgr, saved = make_mgr(monkeypatch)
    seed_trail(mgr)
    items = mgr._intervention_items()
    assert [i["label"] for i in items] == [
        "将LightningDiagnosisTool权重调整为0.1",
        "排除BirdDamageDiagnosisTool",
        "报告修改：增加标题",
    ]
    # 只选第 0、2 项（不含排除）
    await mgr.save_strategy("子集策略", items=[0, 2])
    content = saved["content"]
    assert "0.1" in content and "增加标题" in content
    assert "SKIP — excluded by user preference" not in content  # 未勾选排除


async def test_save_all_when_items_none(monkeypatch):
    mgr, saved = make_mgr(monkeypatch)
    seed_trail(mgr)
    await mgr.save_strategy("全选策略", items=None)
    assert "SKIP — excluded by user preference" in saved["content"]


async def test_prompt_only_after_replay_with_items(monkeypatch):
    """实时轮不弹保存提示；复盘轮带 items 列表。"""
    calls = []

    async def fake_stream(msg, **kwargs):
        calls.append(msg)
        yield {"event_type": "complete", "payload": {
            "report": "# 报告", "summary": {"fault_type": "雷击", "confidence": 0.9}},
            "session_id": "s1"}

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.run_diagnosis(replay=False, text="x")
    assert not [e for e in ws.events if e["type"] == "prompt_save_strategy"]
    mgr.status["commander"] = "idle"
    ws.events.clear()

    async def respond():
        await asyncio.sleep(0.3)
        # 复盘进行中产生干预（trail 在每轮开跑时重置，须在轮内注入）
        mgr._trail("weight", "LightningDiagnosisTool", 0.1)
        # 复盘末段的报告审核询问：直接满意，结束审核循环
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    prompts = [e for e in ws.events if e["type"] == "prompt_save_strategy"]
    assert len(prompts) == 1
    assert prompts[0]["items"][0]["label"] == "将LightningDiagnosisTool权重调整为0.1"


async def test_chat_item_saved_recheck_excluded(monkeypatch):
    """F1：对话异议升格 chat_override，勾选后写入用户自定义数据；recheck 一次性动作不进保存清单。"""
    mgr, saved = make_mgr(monkeypatch)
    mgr.intervention_trail = [
        {"kind": "chat_override", "tool": "LightningDiagnosisTool",
         "value": "雷电要考虑地形", "text": "", "time": "t"},
        {"kind": "recheck", "tool": "WindDiagnosisTool",
         "value": None, "text": "", "time": "t"},
    ]
    items = mgr._intervention_items()
    # recheck 不再出现在可保存清单中
    assert [i["kind"] for i in items] == ["chat_override"]
    assert items[0]["label"] == "LightningDiagnosisTool数据修正(对话):雷电要考虑地形"
    # 勾选 chat_override 项 → markdown 用户自定义数据记录包含对话内容（不再静默丢失）
    await mgr.save_strategy("chat策略", items=[0])
    content = saved["content"]
    assert "## 用户自定义数据记录" in content
    assert "LightningDiagnosisTool数据修正(对话):雷电要考虑地形" in content
