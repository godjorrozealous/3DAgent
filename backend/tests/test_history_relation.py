"""history_relation 预取与缓存：诊断启动即后台预取；缓存命中秒回；失败可重试；换会话失效。"""
import asyncio

import agent_manager
from tests.test_agent_manager import FakeWS


async def areturn(v):
    return v


async def _raise(*a, **kw):
    raise ConnectionError("PLD 8503 不可达")


def _mk(mgr, ws):
    return [e for e in ws.events if e["type"] == "history_relation"]


async def test_history_relation_success(monkeypatch):
    """未预取时点击：立即起预取任务，完成后广播 sections。"""
    monkeypatch.setattr(agent_manager.pld_client, "history_relation",
                        lambda sid: areturn({"success": True,
                                             "sections": [{"title": "一、雅湖线历年情况", "answer": "……"}]}))
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.handle_message({"type": "history_relation"})
    assert mgr._history_task is not None
    await mgr._history_task
    ev = _mk(mgr, ws)[0]
    assert ev["sections"][0]["title"].startswith("一、")


async def test_history_relation_error(monkeypatch):
    monkeypatch.setattr(agent_manager.pld_client, "history_relation", _raise)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.handle_message({"type": "history_relation"})
    await mgr._history_task
    ev = _mk(mgr, ws)[0]
    assert "error" in ev
    assert mgr._history_error


async def test_history_relation_no_session():
    mgr = agent_manager.AgentManager()
    mgr.session_id = None
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.handle_message({"type": "history_relation"})
    ev = _mk(mgr, ws)[0]
    assert ev["error"] == "无活跃会话"


async def test_prefetch_and_broadcast(monkeypatch):
    """预取同会话重复触发为 no-op；完成主动广播（用户未点击也能就绪）。"""
    calls = []

    async def fake(sid):
        calls.append(sid)
        return {"success": True, "sections": [{"title": "T", "answer": "A"}]}

    monkeypatch.setattr(agent_manager.pld_client, "history_relation", fake)
    mgr = agent_manager.AgentManager()
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    mgr._maybe_prefetch_history("s1")
    task = mgr._history_task
    assert task is not None
    mgr._maybe_prefetch_history("s1")  # 同会话：不重复起任务
    assert mgr._history_task is task
    await task
    assert calls == ["s1"]
    assert mgr._history_cache["sections"][0]["title"] == "T"
    # 预取完成主动广播（用户未点击也能就绪）
    assert _mk(mgr, ws)[0]["sections"][0]["title"] == "T"


async def test_degraded_result_not_cached(monkeypatch):
    """降级结果（省份/电压缺失）：广播展示但不缓存，复位 sid 以便后续触发重取。"""
    monkeypatch.setattr(agent_manager.pld_client, "history_relation",
                        lambda sid: areturn({"success": True, "sections": [
                            {"title": "一、雅湖线历年情况", "answer": "……"},
                            {"title": "二、区域同期故障情况",
                             "answer": "该会话诊断未记录省份/电压信息……无法生成此查询。"},
                        ]}))
    mgr = agent_manager.AgentManager()
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    mgr._maybe_prefetch_history("s1")
    await mgr._history_task
    assert mgr._history_cache is None        # 降级结果不进缓存
    assert mgr._history_sid is None          # 复位，允许雷电结果/finish_run 重新触发
    assert _mk(mgr, ws)[0]["sections"][0]["title"].startswith("一、")


async def test_stream_start_does_not_prefetch(monkeypatch):
    """诊断流开始（省份/电压尚未写入会话）不得触发预取，避免降级结果毒化缓存。"""
    async def fake_stream(msg, **kwargs):
        yield {"event_type": "start", "payload": {}, "session_id": "s1"}
        yield {"event_type": "complete",
               "payload": {"report": "# 报告", "summary": {}}, "session_id": "s1"}

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    mgr = agent_manager.AgentManager()
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr._stream_run("诊断", False, {"time": "00:00:00"})
    assert mgr.session_id == "s1"
    assert mgr._history_task is None  # 流开始/完成（无雷电结果）不预取


async def test_lightning_result_triggers_prefetch(monkeypatch):
    """雷电工具结果事件（省份/电压随其写入会话）触发预取。"""
    calls = []

    async def fake(sid):
        calls.append(sid)
        return {"success": True, "sections": [{"title": "T", "answer": "A"}]}

    async def fake_stream(msg, **kwargs):
        yield {"event_type": "start", "payload": {}, "session_id": "s1"}
        yield {"event_type": "result", "session_id": "s1", "payload": {
            "tool": "LightningDiagnosisTool",
            "output": {"structured_data": {"fault_type": "雷击", "confidence": 0.9},
                       "raw_text": "raw"}}}
        yield {"event_type": "complete",
               "payload": {"report": "# 报告", "summary": {}}, "session_id": "s1"}

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "history_relation", fake)
    mgr = agent_manager.AgentManager()
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr._stream_run("诊断", False, {"time": "00:00:00"})
    assert mgr._history_task is not None
    await mgr._history_task
    assert calls == ["s1"]


async def test_finish_run_fallback_prefetch(monkeypatch):
    """本轮未调雷电工具：_finish_run 兜底触发预取。"""
    calls = []

    async def fake(sid):
        calls.append(sid)
        return {"success": True, "sections": []}

    async def fake_session(sid):
        return {"active_weights": {}, "excluded_tools": [], "action_log": []}

    monkeypatch.setattr(agent_manager.pld_client, "history_relation", fake)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr._finish_run({"time": "00:00:00", "report": "# r", "summary": {}}, {}, False)
    assert mgr._history_task is not None
    await mgr._history_task
    assert calls == ["s1"]


async def test_cache_hit_no_pld_call(monkeypatch):
    """缓存命中（复盘与实时同会话）：不再请求 PLD，直接广播缓存。"""
    async def _boom(sid):
        raise AssertionError("不应再次调用 PLD")

    monkeypatch.setattr(agent_manager.pld_client, "history_relation", _boom)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    mgr._history_sid = "s1"
    mgr._history_cache = {"sections": [{"title": "缓存", "answer": "……"}]}
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.handle_message({"type": "history_relation"})
    ev = _mk(mgr, ws)[0]
    assert ev["sections"][0]["title"] == "缓存"
    assert mgr._history_task is None  # 缓存直出，未起新任务


async def test_retry_after_failure(monkeypatch):
    """上次预取失败：再次点击重新发起预取，成功后广播。"""
    state = {"fail": True}

    async def flaky(sid):
        if state["fail"]:
            raise ConnectionError("不可达")
        return {"success": True, "sections": [{"title": "重试成功", "answer": ""}]}

    monkeypatch.setattr(agent_manager.pld_client, "history_relation", flaky)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.handle_message({"type": "history_relation"})
    await mgr._history_task
    assert mgr._history_error
    state["fail"] = False
    await mgr.handle_message({"type": "history_relation"})
    await mgr._history_task
    evs = _mk(mgr, ws)
    assert evs[-1]["sections"][0]["title"] == "重试成功"
    assert mgr._history_error is None  # 重试成功，错误态已随新预取复位


async def test_session_change_invalidates(monkeypatch):
    """换会话：旧预取任务取消、缓存失效、按新会话重新预取。"""
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow(sid):
        started.set()
        await release.wait()
        return {"success": True, "sections": [{"title": f"slow-{sid}", "answer": ""}]}

    async def fast(sid):
        return {"success": True, "sections": [{"title": f"fast-{sid}", "answer": ""}]}

    monkeypatch.setattr(agent_manager.pld_client, "history_relation", slow)
    mgr = agent_manager.AgentManager()
    ws = FakeWS()
    await mgr.connect(ws)
    mgr._maybe_prefetch_history("s1")
    await started.wait()
    old_task = mgr._history_task

    monkeypatch.setattr(agent_manager.pld_client, "history_relation", fast)
    mgr._maybe_prefetch_history("s2")
    assert old_task.cancelled() or old_task.cancelling()
    assert mgr._history_cache is None
    await mgr._history_task
    assert mgr._history_cache["sections"][0]["title"] == "fast-s2"
    release.set()
